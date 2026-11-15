"""Table mapper: code finds candidate headers from the registry, rules decide, SI only breaks ties.

For each downloaded PSI test table, the mapper maps column headers to the keys in the variable
registry (data/variables.yaml) and writes the result to the ledger (data/table_mappings.json),
keyed by the table's file name and SHA-256. SI never reads or writes a value: when two headers
both qualify for one key it points at one of them, and the same rules check its choice.
Rules M-1 to M-5 are in Nimbus/agents/13-table-mapper.md.

    python -m app.nimbus.tables                 # map every table that has no hand-reviewed mapping, write the ledger
    python -m app.nimbus.tables --only PSI-69
    python -m app.nimbus.tables --no-si         # code and rules only (tables with a tie stay unmapped)
    python -m app.nimbus.tables --out other.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.catalog import load_catalog, read_table
from app.config import get_settings
from app.nimbus import spec
from app.psi.harmonise import load_mappings, parse_number
from app.psi.ledger import REASONS, load_registry, registry_hash
from app.psi.units import convert
from app.si import ollama

log = logging.getLogger("spacesweepers.tables")

INITIAL = re.compile(r"\b(init|initial|before)\b|^p?init\b|^pinit\b", re.I)     # a starting condition: M-7 prefers it over the "final" or "after" one
NOT_AMBIENT = re.compile(r"\b(stream|burner|oxidi[sz]er|flow)\b", re.I)
AMBIENT = re.compile(r"ambient", re.I)
CONDITION_KEYS = ("o2_fraction", "pressure_psi")
CELL_UNIT = re.compile(r"([-+]?(?:\d+\.?\d*|\.\d+))\s*([A-Za-z]+)")      # "1 atm": a number and the unit the cell itself states
# The most informative reason first: why the conditions can't be read, then why tests can't be told apart.
CODE_PRIORITY = ["unknown_outcome_values", "multi_value_cells", "sparse_or_non_numeric", "no_unit_in_header", "oxygen_role_unknown", "ambiguous_columns",
                 "no_condition_columns", "test_id_not_unique", "no_test_id"]


def _column(rows: list[tuple[int, list[str]]], index: int) -> list[str]:
    return [(cells[index].strip() if index < len(cells) else "") for _, cells in rows]


def candidates(header: list[str], registry: dict) -> dict[str, list[str]]:
    """Headers whose wording could hold each registry key."""
    return {k: [h for h in dict.fromkeys(header) if h and any(p.search(h) for p in spec["header_re"])] for k, spec in registry.items()}


def _unit(header: str, spec: dict) -> str | None:
    """The unit the header itself states, or None. Units are tried in the registry's order."""
    for unit, patterns in spec["unit_re"].items():
        if any(p.search(header) for p in patterns):
            return unit
    return None


def _convert(number: float, unit: str, key: str) -> float:
    try:
        return convert(number, unit, key)
    except ValueError:
        return number


def _share(values: list[str], spec: dict, unit: str, key: str, in_cell: bool = False) -> tuple[float, float, float]:
    """(share of cells that parse, share of those inside the limits, share of cells holding several values)."""
    parsed, multi = [], 0
    for v in values:
        if not v.strip():
            continue
        text, cell_unit = v, unit
        if in_cell:
            m = CELL_UNIT.fullmatch(v.strip())
            text, cell_unit = (m.group(1), _unit(m.group(2), spec) or unit) if m else (v, unit)
        number, flag = parse_number(text)[:2]
        if flag == "multi":
            multi += 1
        if number is not None:
            parsed.append(_convert(number, cell_unit, key))
    n = len(values)
    inside = sum(spec["min"] <= p <= spec["max"] for p in parsed) / len(parsed) if parsed else 0.0
    return (len(parsed) / n if n else 0.0), inside, (multi / n if n else 0.0)


def _cell_unit(values: list[str], spec: dict) -> str | None:
    """The one unit the cells themselves state ("1 atm"), when at least 95% of the filled cells do."""
    filled = [v.strip() for v in values if v.strip()]
    units = []
    for v in filled:
        m = CELL_UNIT.fullmatch(v)
        units.append(_unit(m.group(2), spec) if m else None)
    if filled and sum(u is not None for u in units) >= 0.95 * len(filled) and len({u for u in units if u}) == 1:
        return next(u for u in units if u)
    return None


def verify(header: list[str], rows: list[tuple[int, list[str]]], pointers: dict[str, str], registry: dict,
           unresolved: dict[str, list[str]] | None = None) -> dict:
    """Check pointers {registry key: header or "none"}. Returns columns, o2_role, checks, evidence, reason_code."""
    checks: list[dict] = []
    add = lambda rule, key, ok, detail, code=None: checks.append({"rule": rule, "variable": key, "ok": ok, "detail": detail, "code": code})  # noqa: E731
    chosen: dict[str, str] = {}
    for key in registry:
        h = str(pointers.get(key) or "none").strip()
        if h == "none":
            continue
        if h not in header:
            add("M-1", key, False, f"{h!r} is not a header of this table.", "not_mappable")
        elif h in chosen.values():
            add("M-1", key, False, f"{h!r} is already used for another variable.", "not_mappable")
        else:
            chosen[key] = h
    index = {h: n for n, h in enumerate(header)}
    columns: dict[str, dict] = {}
    evidence: dict[str, list] = {}
    o2_role = None
    outcome_kind = None
    numeric = [k for k, s in registry.items() if s.get("kind") == "number"]

    if "test_id" not in chosen:
        add("M-5", "test_id", False, "No header looks like a test number.", "no_test_id")
    else:
        values = _column(rows, index[chosen["test_id"]])
        ok = bool(values) and all(values) and len(set(values)) >= 0.9 * len(values)
        add("M-5", "test_id", ok, f"{chosen['test_id']!r}: {len(set(values))} different values in {len(values)} rows.", None if ok else "test_id_not_unique")
        if ok:
            columns["test_id"] = {"column": chosen["test_id"]}

    if "fuel" in chosen:
        values = _column(rows, index[chosen["fuel"]])
        ok = bool(values) and sum(bool(v) for v in values) >= 0.5 * len(values)
        add("M-3", "fuel", ok, f"{chosen['fuel']!r} names a fuel or material in most rows." if ok else f"{chosen['fuel']!r} is mostly empty.")
        if ok:
            columns["fuel"] = {"column": chosen["fuel"], "kind": "text"}

    for key in numeric:
        spec = registry[key]
        if key not in chosen:
            if unresolved and key in unresolved:
                add("M-1", key, False, f"Several headers could hold {key} ({', '.join(unresolved[key])}) and none was chosen.", "ambiguous_columns")
            continue
        h = chosen[key]
        values = _column(rows, index[h])
        unit, in_cell = _unit(h, spec), False
        if unit is None:                                        # M-2b: the cells may state the unit themselves
            unit = _cell_unit(values, spec)
            in_cell = unit is not None
        if unit is None:
            add("M-2", key, False, f"{h!r} states no unit (in the header or in its cells), so none is assumed.", "no_unit_in_header")
            continue
        share, inside, multi = _share(values, spec, unit, key, in_cell)
        ok = share >= 0.8 and inside >= 0.95
        code = None if ok else ("multi_value_cells" if multi >= 0.3 else "sparse_or_non_numeric")
        add("M-3", key, ok, f"{h!r} in {unit}{' (stated in each cell)' if in_cell else ''}: {share:.0%} of rows are numbers, {inside:.0%} of them physically plausible"
            + (f", {multi:.0%} hold several values." if multi else "."), code)
        if not ok:
            continue
        if spec.get("needs_ambient"):
            where = h if AMBIENT.search(h) else next((x for x in header if AMBIENT.search(x)), None)
            role_ok = where is not None and not NOT_AMBIENT.search(h)
            add("M-4", key, role_ok, f"The table says its oxygen is ambient ({where!r})." if role_ok else
                "Nothing in the headers says this oxygen is the surrounding air, so it is not mapped.", None if role_ok else "oxygen_role_unknown")
            if not role_ok:
                continue
            o2_role = "ambient"
        columns[key] = {"column": h, "kind": "number", "unit": unit, "min": spec["min"], "max": spec["max"]}
        if in_cell:
            columns[key]["unit_in_cell"] = True
        samples = []
        for row_no, cells in rows[:3]:
            raw = cells[index[h]].strip() if index[h] < len(cells) else ""
            if in_cell:
                m = CELL_UNIT.fullmatch(raw)
                number = parse_number(m.group(1))[0] if m else None
                cell_unit = (_unit(m.group(2), spec) or unit) if m else unit
            else:
                number, cell_unit = (parse_number(raw)[0] if raw else None), unit
            if number is not None:
                samples.append({"row": row_no, "raw": raw, "value": round(_convert(number, cell_unit, key), 6)})
        evidence[key] = samples

    # M-8: gas columns that add up to 1 are mole fractions of one gas mixture; if they don't, the minor gases are not trusted.
    gases = [k for k in ("o2_fraction", "n2_fraction", "he_fraction", "co2_fraction") if k in columns]
    composition = None
    if len(gases) >= 3:
        within = total = 0
        for _, cells in rows:
            vals = []
            for k in gases:
                c = columns[k]
                raw = cells[index[c["column"]]].strip() if index[c["column"]] < len(cells) else ""
                n = parse_number(raw)[0] if raw else None
                vals.append(None if n is None else _convert(n, c["unit"], k))
            if None in vals:
                continue
            total += 1
            within += abs(sum(vals) - 1) <= 0.03
        composition = {"columns": [columns[k]["column"] for k in gases], "rows": total, "within": within, "tolerance": 0.03}
        ok = total > 0 and within >= 0.95 * total
        add("M-8", "gases", ok, f"The gas columns add up to 1 (within 0.03) in {within} of {total} rows: they are mole fractions of one gas mixture."
            if ok else f"The gas columns add up to 1 in only {within} of {total} rows, so the minor gases are not mapped.", None if ok else "not_mappable")
        if not ok:
            for k in gases:
                if k != "o2_fraction":
                    columns.pop(k, None)

    # M-6: an outcome column is mapped only if every raw value in it is in the registry's vocabulary for that outcome.
    for key, spec in registry.items():
        if spec.get("kind") != "category" or key not in chosen:
            continue
        h = chosen[key]
        raw_values = {v.strip().lower() for v in _column(rows, index[h]) if v.strip()}
        unknown = sorted(raw_values - set(spec["values"]))
        if unknown:
            add("M-6", key, False, f"{h!r} has values the registry doesn't define: {', '.join(repr(u) for u in unknown[:5])}. Not mapped; review them.", "unknown_outcome_values")
            continue
        add("M-6", key, True, f"{h!r}: all {len(raw_values)} different values are defined ({', '.join(sorted(raw_values))}).")
        columns[spec["harmonised_as"]] = {"column": h, "kind": "category", "values": dict(spec["values"])}
        if spec.get("outcome_kind"):
            outcome_kind = spec["outcome_kind"]

    mapped = "test_id" in columns and any(k in columns for k in CONDITION_KEYS)
    code = None
    if not mapped:
        if not any(k in chosen for k in CONDITION_KEYS) and not any(c["code"] == "ambiguous_columns" for c in checks):
            add("M-1", "conditions", False, "No oxygen or pressure header was found.", "no_condition_columns")
        failed = {c["code"] for c in checks if not c["ok"] and c["code"]}
        code = next((c for c in CODE_PRIORITY if c in failed), "not_mappable")
    return {"columns": columns, "o2_role": o2_role, "checks": checks, "evidence": evidence, "mapped": mapped, "reason_code": code,
            "outcome_kind": outcome_kind, "composition": composition}


async def pick(http, url, model, inv, table_file, header, rows, timeout, ties: dict[str, list[str]]) -> dict:
    """Ask SI to choose between candidate headers. Only the tied keys are asked about, and SI can say none."""
    agent = spec.agent("13-table-mapper.md")
    schema = json.loads(json.dumps(agent.output_schema))
    for q in list(schema["properties"]):
        schema["properties"][q]["enum"] = [*ties.get(q, []), "none"]
    user = agent.user_template.format(
        id=inv["id"], title=inv["title"], file=Path(table_file).name,
        headers="\n".join(f"{n}. {h}" for n, h in enumerate(header, 1) if h),
        rows="\n".join(" | ".join(c.strip() for c in cells) for _, cells in rows[:3]))
    return await ollama.chat_json(http, url, model, agent.system_prompt, user, schema, timeout, agent.meta.get("options"))


async def run(data_dir: Path, model: str, only: list[str] | None, out_path: Path, use_si: bool = True) -> dict:
    settings = get_settings()
    catalog = load_catalog(data_dir)
    snapshot = data_dir / "snapshot"
    registry = load_registry(data_dir / "variables.yaml")
    quantity = {k: s["quantity"] for k, s in registry.items()}
    hand = load_mappings(data_dir / "mappings")
    existing = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {"tables": {}}
    tables = existing["tables"]
    for stale in [n for n in tables if n in hand]:                # a hand-reviewed mapping replaces any generated entry for the same table
        tables.pop(stale)
    async with httpx.AsyncClient() as http:
        if use_si:
            installed = await ollama.installed_models(http, settings.ollama_url)
            use_si = installed is not None and ollama.is_installed(model, installed)
            if not use_si:
                log.warning("SI model %r isn't available; tables with a tie stay unmapped.", model)
        for inv in catalog.ordered():
            if only and inv["id"] not in only:
                continue
            for table in catalog.manifest["investigations"][inv["id"]]["tables"]:
                name = Path(table["file"]).name
                if table.get("superseded_by"):
                    continue                                  # counted in the workbook table
                if name in hand:
                    continue                                  # hand-reviewed mappings are never overwritten
                header, rows = read_table(snapshot, table)
                found = candidates(header, registry)
                pointers = {k: (v[0] if len(v) == 1 else "none") for k, v in found.items()}
                ties = {k: v for k, v in found.items() if len(v) > 1}
                provenance = "rules"
                for k in list(ties):                                      # M-7: the starting condition, when exactly one tied header is one
                    starting = [h for h in ties[k] if INITIAL.search(h) or re.match(r"^pinit\b", h, re.I)]
                    if len(starting) == 1 and registry[k].get("kind") == "number":
                        pointers[k] = starting[0]
                        ties.pop(k)
                        provenance = "rules (starting condition preferred)"
                if ties and use_si:
                    try:
                        asked = await pick(http, settings.ollama_url, model, inv, table["file"], header, rows, settings.si_timeout_seconds,
                                           {quantity[k]: v for k, v in ties.items()})
                        pointers.update({k: asked.get(quantity[k], "none") for k in ties if asked.get(quantity[k]) in ties[k]})
                        provenance = "rules + SI tie-break"
                    except ollama.SIError as e:
                        log.warning("%s: SI didn't answer (%s); tied headers stay unmapped.", name, e)
                result = verify(header, rows, pointers, registry, {k: v for k, v in ties.items() if pointers[k] == "none"})
                entry = {"investigation": inv["id"], "sha256": table["sha256"], "s3_version_id": table.get("s3_version_id"),
                         "bytes": table.get("bytes"), "rows": len(rows), "status": "mapped" if result["mapped"] else "not mappable",
                         "reason_code": result["reason_code"], "reason": REASONS.get(result["reason_code"]) if result["reason_code"] else None,
                         "provenance": provenance, "checks": result["checks"], "evidence": result["evidence"]}
                if result["mapped"]:
                    cols = {k: v for k, v in result["columns"].items() if k != "test_id"}
                    mapping = {"file": name, "label": Path(name).stem.split("_", 1)[-1], "test_id": result["columns"]["test_id"]["column"],
                               "columns": cols, "o2_role": result["o2_role"]}
                    fuel_class = _fuel_class(rows, header, result["columns"], catalog.vocabulary)
                    if fuel_class:
                        mapping["fuel_class"] = fuel_class
                    if result["o2_role"]:
                        mapping["o2_role_reason"] = next(c["detail"] for c in result["checks"] if c["rule"] == "M-4" and c["ok"])
                    if result["outcome_kind"]:
                        mapping["outcome_kind"] = result["outcome_kind"]
                    if result["composition"]:
                        mapping["composition_check"] = result["composition"]
                    entry["mapping"] = mapping
                    entry["not_mapped"] = [k for k in CONDITION_KEYS if k not in cols]
                tables[name] = entry
                log.info("%s %-44s %s", inv["id"], name[:44], ("mapped: " + ", ".join(result["columns"])) if result["mapped"] else f"not mappable: {result['reason_code']}")
    out = {"generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "registry_hash": registry_hash(data_dir / "variables.yaml"),
           "model": model if use_si else None,
           "note": (f"Code finds the candidate columns and rules M-1 to M-5 decide; {model} (SI) is asked only to break ties between candidates, "
                    "and never invents a mapping." if use_si else "Mapped by code and rules M-1 to M-5 only; no SI was used for this ledger."),
           "tables": dict(sorted(tables.items()))}
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


def _fuel_class(rows, header, columns, vocabulary) -> str | None:
    if "fuel" not in columns:
        return None
    classes = {term: cls for cls, terms in vocabulary["fuels"].items() for term in terms}
    found = set()
    for value in set(_column(rows, header.index(columns["fuel"]["column"]))):
        for term in sorted(classes, key=len, reverse=True):
            if value and re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", value, re.I):
                found.add(classes[term])
                break
    return found.pop() if len(found) == 1 else None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Map PSI test-table columns to the variable registry and write the ledger.")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--no-si", action="store_true", help="code and rules only; no model call")
    parser.add_argument("--out", type=Path, help="ledger path (default data/table_mappings.json)")
    args = parser.parse_args()
    settings = get_settings()
    asyncio.run(run(settings.data_dir, settings.si_model, args.only, args.out or settings.data_dir / "table_mappings.json", not args.no_si))
