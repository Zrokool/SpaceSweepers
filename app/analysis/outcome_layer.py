"""Document-derived outcomes: the layer of test outcomes that were read from a lab's free-text notes.

They are stored as references (table row + the table's SHA-256 -> class and quote) by app/nimbus/outcomes.py. Here they are
attached to the harmonised tests with the quality flag `document_text`, which every table statistic ignores: they are counted
and drawn as their own layer and never enter a model, skill check or pattern.
"""

from __future__ import annotations

import json
from pathlib import Path

OUTCOME_KIND = "burn"
SOURCE = "document text"
FLAG = "document_text"


def load(data_dir: Path) -> dict:
    path = data_dir / "outcome_evidence.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def apply(tests: list[dict], psi_id: str, table_name: str, table_sha: str, evidence: dict) -> dict:
    """Attach stored outcomes to this table's tests. Returns {"applied": n, "stale": bool}; a table that changed gets nothing."""
    entry = evidence.get(psi_id)
    if not entry or entry["table"] != table_name:
        return {"applied": 0, "stale": False}
    if entry["sha256"] != table_sha:
        return {"applied": 0, "stale": True}                 # the table changed since the outcomes were read: data refresh needed
    n = 0
    for t in tests:
        e = entry["rows"].get(str(t["row"]))
        if e and e["status"] == "evidence":
            t["values"]["outcome"] = {"variable": "outcome", "raw": e["quote"], "value": e["class"], "unit": None, "flag": FLAG, "lo": None, "hi": None}
            t["outcome_kind"], t["outcome_source"], t["outcome_quote"], t["outcome_sentence"] = OUTCOME_KIND, SOURCE, e["quote"], e["id"]
            n += 1
    return {"applied": n, "stale": False}
