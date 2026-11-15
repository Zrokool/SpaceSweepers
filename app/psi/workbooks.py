"""PSI spreadsheet workbooks: which are left out, and (below, as they are added) how a workbook becomes one data table.

Rule: one stored copy of every fact. The recipes live in data/workbooks.yaml and are reviewed by hand.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

from app.config import ROOT

RECIPES = ROOT / "data" / "workbooks.yaml"


@lru_cache
def load(path: Path = RECIPES) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def not_read(path: Path = RECIPES) -> dict[str, str]:
    """{file name ending: reason} for workbooks that are deliberately never stored or indexed."""
    return dict(load(path).get("not_read") or {})


# ------------------------------------------------------------------ one canonical table per workbook
import csv
import hashlib
import io
import json
import logging
import re

from app.psi import documents

log = logging.getLogger("spacesweepers.workbooks")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _header_row(grid: dict[int, dict[int, str]], key: str) -> int:
    """The row that names the columns: the first row with a cell equal to the key column's name."""
    for row, cells in sorted(grid.items()):
        if any(v.strip() == key for v in cells.values()):
            return row
    raise ValueError(f"no header row contains {key!r}")


def _sheet_rows(grid: dict[int, dict[int, str]], key: str, key_pattern: re.Pattern) -> tuple[list[str], list[tuple[str, dict[str, str]]]]:
    """(column names, [(key, {column: value})]) for one sheet. Names are the header cells, trimmed."""
    head = _header_row(grid, key)
    names = {c: v.strip() for c, v in grid[head].items()}
    key_col = next(c for c, v in names.items() if v == key)
    rows = []
    for r, cells in sorted(grid.items()):
        if r <= head or key_col not in cells or not key_pattern.match(cells[key_col].strip()):
            continue
        row = {names[c]: v for c, v in cells.items() if c in names}
        row[key] = cells[key_col].strip()                               # the identifier is trimmed; every other value stays as written
        rows.append((row[key], row))
    return list(names.values()), rows


def build_table(recipe: dict, data: bytes) -> tuple[list[str], list[dict[str, str]], dict]:
    """Join a workbook's sheets on the key. Returns (columns, rows, report). Nothing is guessed: a key missing from a
    sheet leaves its cells blank, and every unmatched or repeated key is reported."""
    sheets = dict(documents.read_sheets(data))
    pattern = re.compile(recipe.get("key_pattern", r".+"))
    key = recipe["key"]
    names, base = _sheet_rows(sheets[recipe["sheets"][0]], key, pattern)
    columns = list(dict.fromkeys(names))
    rows = [(k, dict(v)) for k, v in base]                           # every row is kept, even when a key repeats
    counts = {k: [x for x, _ in base].count(k) for k, _ in base}
    report = {"sheets": recipe["sheets"], "key": key, "base_rows": len(base), "repeated_keys": sorted(k for k, n in counts.items() if n > 1),
              "unmatched": {}, "missing": {}}
    for sheet in recipe["sheets"][1:]:
        other_names, other = _sheet_rows(sheets[sheet], key, pattern)
        renamed = {n: (n if n not in columns or n == key else f"{n} [{sheet}]") for n in other_names}
        columns += [renamed[n] for n in other_names if renamed[n] not in columns]
        by_key: dict[str, list[dict[str, str]]] = {}
        for k, cells in other:
            by_key.setdefault(k, []).append(cells)
        for k, cells in rows:
            for match in by_key.get(k, [])[:1]:                      # the first row of the other sheet for this key
                cells.update({renamed[n]: v for n, v in match.items() if n != key})
        report["unmatched"][sheet] = sorted(set(by_key) - {k for k, _ in rows})
        report["missing"][sheet] = sorted({k for k, _ in rows} - set(by_key))
    report["rows"] = len(rows)
    return columns, [cells for _, cells in rows], report


def to_csv(columns: list[str], rows: list[dict[str, str]]) -> bytes:
    out = io.StringIO(newline="")
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(columns)
    for r in rows:
        writer.writerow([r.get(c, "") for c in columns])
    return out.getvalue().encode("utf-8")


def build_simulations(recipe: dict, data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    """A 'list of data files' sheet written as several blocks, each with its own header row. Values are kept exactly as written."""
    grid = dict(documents.read_sheets(data))[recipe["sheet"]]
    columns: list[str] = []
    rows: list[dict[str, str]] = []
    header: dict[int, str] | None = None
    for _, cells in sorted(grid.items()):
        if cells.get(2, "").strip() == "Fuel":                       # a new block starts at its header row
            header = {c: v.strip() for c, v in cells.items()}
            header.setdefault(11, "Figure")
            columns += [h for h in header.values() if h not in columns]
            continue
        if header and cells.get(2):
            row = {header[c]: v for c, v in cells.items() if c in header}
            if 9 in cells and 9 not in header:
                row["Data File"] = cells[9]
            if 10 in cells and 10 not in header:
                row["Reference"] = cells[10]
            if 11 in cells:
                row["Figure"] = cells[11]
            columns += [c for c in row if c not in columns]
            rows.append(row)
    for name in ("Data File", "Reference", "Figure"):
        if name not in columns:
            columns.append(name)
    return columns, rows


def apply(psi_id: str, entry: dict, docs_dir: Path, snapshot: Path, path: Path = RECIPES) -> list[str]:
    """Turn this investigation's workbooks into tables, once. Updates the manifest `entry` and the files in `snapshot`.

    A workbook that becomes a table has its text dropped (one stored copy of every fact), and a CSV it fully contains is
    marked `superseded_by`. Returns messages describing what was done."""
    recipes, done = load(path), []
    for recipe in [r for r in recipes.get("tables", []) if r["investigation"] == psi_id]:
        source = docs_dir / psi_id / recipe["workbook"]
        if not source.exists():
            done.append(f"{recipe['workbook']}: workbook not in the local cache; skipped")
            continue
        data = source.read_bytes()
        columns, rows, report = build_table(recipe, data)
        csv_bytes = to_csv(columns, rows)
        target = snapshot / "tables" / psi_id / recipe["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(csv_bytes)
        entry["tables"] = [t for t in entry["tables"] if Path(t["file"]).name != recipe["name"]]
        entry["tables"].append({"file": f"tables/{psi_id}/{recipe['name']}", "bytes": len(csv_bytes), "sha256": _sha256(csv_bytes), "s3_version_id": None,
                                "kept_from_earlier_sync": False, "source": "workbook", "workbook": recipe["workbook"], "workbook_sha256": _sha256(data),
                                "recipe_hash": _sha256(json.dumps(recipe, sort_keys=True).encode())[:16], "join": report})
        if recipe.get("supersedes"):
            for t in entry["tables"]:
                if Path(t["file"]).name == recipe["supersedes"]:
                    t["superseded_by"] = f"tables/{psi_id}/{recipe['name']}"
        _drop_text(entry, recipe["workbook"], snapshot, "converted to a table", f"its cells are in {recipe['name']} (one stored copy of every fact)")
        done.append(f"{recipe['name']}: {len(rows)} tests from {len(recipe['sheets'])} sheet(s)")
    for recipe in [r for r in recipes.get("simulations", []) if r["investigation"] == psi_id]:
        source = docs_dir / psi_id / recipe["workbook"]
        if not source.exists():
            continue
        data = source.read_bytes()
        columns, rows = build_simulations(recipe, data)
        csv_bytes = to_csv(columns, rows)
        target = snapshot / "simulations" / psi_id / recipe["name"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(csv_bytes)
        entry["simulations"] = [{"file": f"simulations/{psi_id}/{recipe['name']}", "bytes": len(csv_bytes), "sha256": _sha256(csv_bytes), "rows": len(rows),
                                 "workbook": recipe["workbook"], "workbook_sha256": _sha256(data)}]
        _drop_text(entry, recipe["workbook"], snapshot, "kept as a list", f"its rows are in {recipe['name']} (one stored copy of every fact)")
        done.append(f"{recipe['name']}: {len(rows)} data-file entries")
    return done + tidy_not_read(psi_id, entry, snapshot, path)


def _drop_text(entry: dict, name: str, snapshot: Path, handling: str, reason: str) -> None:
    """The workbook is no longer a document: its extracted text is not stored or indexed (the table holds the same cells).
    It is recorded under `workbooks` with what became of it."""
    doc = next((d for d in entry.get("documents", []) if Path(d["file"]).name == name), None)
    if doc is None:
        return
    if doc.get("text_file"):
        (snapshot / doc["text_file"]).unlink(missing_ok=True)
    entry["documents"] = [d for d in entry["documents"] if d is not doc]
    entry["workbooks"] = [w for w in entry.get("workbooks", []) if w["file"] != doc["file"]] + [
        {"file": doc["file"], "folder": doc.get("folder"), "bytes": doc.get("bytes"), "handling": handling, "reason": reason}]


def tidy_not_read(psi_id: str, entry: dict, snapshot: Path, path: Path = RECIPES) -> list[str]:
    """Move workbooks that data/workbooks.yaml says are not stored out of `documents` (for a snapshot made before they were listed)."""
    moved = []
    for key, why in not_read(path).items():
        for doc in [d for d in entry.get("documents", []) if d["file"].endswith(key)]:
            _drop_text(entry, Path(doc["file"]).name, snapshot, "not stored", why)
            moved.append(f"{doc['file']}: not stored ({why})")
    return moved


if __name__ == "__main__":
    import argparse

    from app.config import get_settings
    parser = argparse.ArgumentParser(description="Build the workbook tables from the local PSI document cache (no download).")
    parser.add_argument("--snapshot", type=Path, default=get_settings().snapshot_dir)
    parser.add_argument("--docs", type=Path, default=get_settings().cache_dir / "psi-docs")
    args = parser.parse_args()
    manifest_path = args.snapshot / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for psi_id, entry in manifest["investigations"].items():
        for line in apply(psi_id, entry, args.docs, args.snapshot):
            print(f"{psi_id}: {line}")
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
