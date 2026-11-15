"""Categorize every PSI test table: its experiment family and how ready it is for analysis.

Rules are in data/taxonomy.yaml and are tried in order. A table's family comes from its own column
headers first, then its investigation's text; the tier comes from what the mapping found. Each result
carries the headers or words it matched, so a reader can check it. No SI.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml


@lru_cache
def load_taxonomy(path: Path) -> dict:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    for fam in doc["families"]:
        fam["col_re"] = [re.compile(p, re.I) for p in fam.get("columns_any", [])]
        fam["text_re"] = [re.compile(rf"\b{p}", re.I) for p in fam.get("text_any", [])]
    doc["cont_re"] = [re.compile(p, re.I) for p in doc["continuous_outcomes"]]
    doc["plan_re"] = [re.compile(p, re.I) for p in doc["plan_counts"]]
    return doc


def classify(taxonomy: dict, header: list[str], inv: dict, entry: dict) -> dict:
    """{family, family_label, family_evidence, tier, tier_reason} for one table.

    `entry` is the table's catalog coverage entry: status "parsed", or "not mappable" with a reason code.
    """
    heads = [h.strip() for h in header if h.strip()]
    text = " ".join(str(inv.get(k) or "") for k in ("title", "approach", "objective"))
    family, evidence = None, []
    for fam in taxonomy["families"]:
        cols = [h for h in heads if any(p.search(h) for p in fam["col_re"])]
        words = [p.pattern[2:] for p in fam["text_re"] if p.search(text)] if not cols else []
        if cols or words:
            family, evidence = fam, [f"column {c!r}" for c in cols[:3]] + [f"record text mentions {w!r}" for w in words[:2]]
            break
    if family is None:
        family, evidence = {"key": "unclassified", "label": "Unclassified"}, []
    outcome_cols = [h for h in heads if any(p.search(h) for p in taxonomy["cont_re"])]
    plan_cols = [h for h in heads if any(p.search(h) for p in taxonomy["plan_re"])]
    parsed = entry["status"] == "parsed"
    if entry["status"] == "superseded":
        return {"family": family["key"], "family_label": family["label"], "family_evidence": evidence, "tier": "S", "tier_reason": entry["reason"]}
    has_category = parsed and entry.get("has_outcome")
    if has_category:
        tier, why = "A", "Conditions and a categorical outcome are mapped for every test."
    elif plan_cols or entry.get("reason_code") == "multi_value_cells":
        tier, why = "D", f"Test plan: {('count column ' + repr(plan_cols[0])) if plan_cols else 'several values in one cell'}."
    elif outcome_cols and family["key"] != "not_a_test_table":
        tier, why = "B", (f"Measured results recorded ({', '.join(repr(c) for c in outcome_cols[:3])}) but no categorical outcome is mapped."
                          + (" Oxygen or pressure is mapped." if parsed else ""))
    elif parsed:
        tier, why = "C", "Oxygen or pressure is mapped; no outcome column."
    else:
        tier, why = "E", entry.get("reason") or "No oxygen or pressure column."
    return {"family": family["key"], "family_label": family["label"], "family_evidence": evidence,
            "tier": tier, "tier_reason": why}
