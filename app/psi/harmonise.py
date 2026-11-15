"""Turn PSI test tables into harmonised values, without silently cleaning anything.

Every value keeps its raw text, parsed number, unit, quality flag, source file
and row. Column meanings come from reviewed mapping files (data/mappings/PSI-xx.yaml),
never from guesses in code.

Quality flags:
  ok          parsed cleanly
  approx      written as approximate ("~21")
  range       a range ("21.5 - 21.7"); the value is the midpoint, lo/hi are kept
  multi       several values in one cell ("0.17; 0.21; 0.25"); no single value
  missing     empty, "none", "-", "n/a"
  implausible parsed, but outside the mapping's plausible limits (e.g. negative ppm)
  unparsed    text that isn't a number
  document_text  an outcome read from a lab's free-text note (app/nimbus/outcomes.py); counted as its own layer, never in a statistic
A row with no test id is a note row, not a test: it is counted and kept out of the data.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import yaml

from app.psi.units import convert

MISSING = {"", "-", "--", "none", "n/a", "na", "nan", "tbd", "?"}
NUMBER = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?"
RANGE = re.compile(rf"^({NUMBER})\s*(?:-|–|to)\s*({NUMBER})$")


@dataclass
class Value:
    variable: str
    raw: str
    value: float | str | None
    unit: str | None
    flag: str
    lo: float | None = None
    hi: float | None = None


def parse_number(raw: str) -> tuple[float | None, str, float | None, float | None]:
    """(value, flag, lo, hi) for one cell of text."""
    text = raw.strip()
    if text.lower() in MISSING:
        return None, "missing", None, None
    flag = "ok"
    if text[0] in "~≈":
        text, flag = text[1:].strip(), "approx"
    text = text.rstrip("%").strip()
    if re.fullmatch(NUMBER, text):
        return float(text), flag, None, None
    if ";" in text or "," in text:
        return None, "multi", None, None
    m = RANGE.match(text)
    if m:
        lo, hi = sorted((float(m.group(1)), float(m.group(2))))
        return (lo + hi) / 2, "range", lo, hi
    return None, "unparsed", None, None


def parse_value(variable: str, spec: dict, raw: str) -> Value:
    kind = spec.get("kind", "number")
    text = (raw or "").strip()
    if kind == "text":
        return Value(variable, raw, text or None, None, "ok" if text else "missing")
    if kind == "category":
        if text.lower() in MISSING and text.lower() not in spec["values"]:
            return Value(variable, raw, None, None, "missing")
        mapped = spec["values"].get(text.lower())
        return Value(variable, raw, mapped, None, "ok" if mapped else "unparsed")
    if kind == "category_from_number":                     # a count read as a category: "Reignitions" 0 -> no_reignition, 3 -> reignited
        number, flag, _, _ = parse_number(text)
        if number is None:
            return Value(variable, raw, None, None, flag)
        return Value(variable, raw, spec["above"] if number > spec.get("threshold", 0) else spec["otherwise"], None, "ok")
    unit = spec.get("unit")
    if spec.get("unit_in_cell"):                           # the cell states its own unit: "1 atm"
        m = re.fullmatch(rf"({NUMBER})\s*([A-Za-z]+)", text)
        if not m:
            return Value(variable, raw, None, unit, "missing" if text.lower() in MISSING else "unparsed")
        text, unit = m.group(1), m.group(2).lower()
    number, flag, lo, hi = parse_number(text)
    if number is None:
        return Value(variable, raw, None, unit, flag)
    number, lo, hi = (None if v is None else convert(v, unit, variable) for v in (number, lo, hi))
    canonical = "psi" if variable == "pressure_psi" else "mole_fraction" if variable.endswith("_fraction") else unit
    if not spec.get("min", float("-inf")) <= number <= spec.get("max", float("inf")):
        flag = "implausible"
    return Value(variable, raw, round(number, 6), canonical, flag,
                 None if lo is None else round(lo, 6), None if hi is None else round(hi, 6))


def load_mappings(mappings_dir: Path) -> dict[str, dict]:
    """{table file name: mapping}, with the investigation id added to each."""
    out: dict[str, dict] = {}
    for path in sorted(mappings_dir.glob("PSI-*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for table in doc["tables"]:
            for variable, spec in table["columns"].items():
                bad = [k for k in spec.get("values", {}) if not isinstance(k, str)]
                if bad:  # YAML reads bare yes/no as booleans; a mapping like that would match nothing
                    raise ValueError(f"{path.name}: {variable} has non-text category keys {bad}; quote them")
            out[table["file"]] = {**table, "investigation": doc["investigation"]}
    return out


def harmonise_table(data: bytes, mapping: dict, source_file: str) -> dict:
    """Parse one table. Returns {"tests": [...], "coverage": {...}}."""
    reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig", errors="replace")))
    header = reader.fieldnames or []
    columns = mapping["columns"]
    missing_columns = [s["column"] for s in columns.values() if s["column"] not in header]
    if mapping["test_id"] not in header:
        missing_columns.append(mapping["test_id"])
    tests, notes, blank, flags = [], 0, 0, {}
    for row_no, row in enumerate(reader, start=2):  # row 1 is the header
        if not any((v or "").strip() for v in row.values()):
            blank += 1
            continue
        test_id = (row.get(mapping["test_id"]) or "").strip()
        if not test_id:
            notes += 1
            continue
        values = {}
        for variable, spec in columns.items():
            if spec["column"] not in header:
                continue
            v = parse_value(variable, spec, row.get(spec["column"]) or "")
            flags[v.flag] = flags.get(v.flag, 0) + 1
            values[variable] = asdict(v)
        tests.append({"investigation": mapping["investigation"], "test_id": test_id, "file": source_file,
                      "row": row_no, "table": mapping.get("label", source_file),
                      "fuel_class": mapping.get("fuel_class"), "o2_role": mapping.get("o2_role"),
                      "outcome_kind": mapping.get("outcome_kind"),
                      "values": values})
    mapped = {s["column"] for s in columns.values()} | {mapping["test_id"]}
    return {"tests": tests,
            "coverage": {"file": source_file, "tests": len(tests), "note_rows": notes, "blank_rows": blank,
                         "flags": flags, "columns_unmapped": [h for h in header if h and h not in mapped],
                         "columns_missing": missing_columns}}
