"""Why only part of PSI can be charted: what the tier-B tables hold, and how much data sits behind each investigation. No SI.

Everything is computed from the snapshot and the variable registry, so the Sources page never states a number that is not in the data.
"""

from __future__ import annotations

from pathlib import Path

from app.analysis.sweeper import _value
from app.catalog import Catalog, read_table
from app.nimbus.tables import candidates

ANALYZED_FEASIBLE_MB = 50.0          # an Analyzed Data folder up to this size is small enough to download and review
RAW_FEASIBLE_MB = 2_000.0


def table_holdings(catalog: Catalog, snapshot: Path, registry: dict, tier: str = "B") -> list[dict]:
    """For every table in a tier: how many rows, what its columns are, and whether it can sit on the oxygen × pressure charts."""
    out = []
    for inv in catalog.ordered():
        entries = {e["file"].rsplit("/", 1)[-1]: e for e in catalog.manifest["investigations"][inv["id"]]["tables"]}
        for t in inv["tables"]:
            if t.get("tier") != tier or t["file"] not in entries:
                continue
            header, rows = read_table(snapshot, entries[t["file"]])
            cand = candidates(header, registry)
            has_o2, has_p = bool(cand.get("o2_fraction")), bool(cand.get("pressure_psi"))
            placed = sum(1 for x in catalog.tests if x["file"] == t["file"] and _value(x, "o2_fraction") is not None and _value(x, "pressure_psi") is not None)
            missing = [name for name, ok in (("oxygen", has_o2), ("pressure", has_p)) if not ok]
            out.append({"psi": inv["id"], "name": inv["name"], "file": t["file"], "rows": len(rows), "columns": [h for h in header if h][:7],
                        "has_oxygen": has_o2, "has_pressure": has_p, "on_charts": placed,
                        "why_not": None if placed else (f"No {' or '.join(missing)} column." if missing else "Oxygen and pressure columns exist but no test has a usable value for both.")})
    return out


def data_layers(catalog: Catalog) -> list[dict]:
    """Per investigation: the test table, and the Raw Data and Analyzed Data PSI lists but we have not downloaded, with sizes."""
    out = []
    for inv in catalog.ordered():
        inv_files = inv["file_inventory"] or {}
        raw, analyzed = inv_files.get("Raw Data"), inv_files.get("Analyzed Data")
        if not (raw or analyzed):
            continue
        mb = lambda f: round(f["bytes"] / 1e6, 1) if f else None   # noqa: E731
        a_mb, r_mb = mb(analyzed), mb(raw)
        stored = len(catalog.manifest["investigations"][inv["id"]].get("analyzed", []))
        out.append({"psi": inv["id"], "name": inv["name"], "table_rows": inv["table_rows"], "stored": stored,
                    "analyzed": None if not analyzed else {"files": analyzed["files"], "mb": a_mb, "types": sorted({n.rsplit(".", 1)[-1].lower() for n in analyzed["names"] if "." in n}),
                                                           "feasible": a_mb <= ANALYZED_FEASIBLE_MB},
                    "raw": None if not raw else {"files": raw["files"], "mb": r_mb, "feasible": r_mb <= RAW_FEASIBLE_MB}})
    return sorted(out, key=lambda r: (r["analyzed"] is None, r["analyzed"]["mb"] if r["analyzed"] else 0))
