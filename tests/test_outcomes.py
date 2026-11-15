"""Document-derived outcomes: SI points, code classifies; the layer never reaches a table statistic."""

import asyncio
import csv
import json
from pathlib import Path

from app.analysis import outcome_layer, sweeper
from app.catalog import load_catalog
from app.nimbus import outcomes
from app.si import ollama

DATA = Path(__file__).resolve().parent.parent / "data"
HABITAT = {"label": "ISS", "o2": [0.2, 0.25], "pressure_psi": [14.5, 14.9]}


def test_classifier_cues_and_negation():
    assert outcomes.classify("No ignition on this test.") == "no_ignition"
    assert outcomes.classify("Sample did not ignite but smoked.") == "no_ignition"
    assert outcomes.classify("Ignited and spread slowly upstream.") == "burned"
    assert outcomes.classify("It did not burn.") is None                        # negated and no ignition phrase: not a claim of burning
    assert outcomes.classify("Don turned the fan off.") is None


def test_failure_cue_wins_inside_one_sentence():
    assert outcomes.classify("Tried to ignite, no ignition, then burned the igniter wire.") == "no_ignition"


def test_decide_pointer_must_be_a_candidate_and_code_decides_the_class():
    note = "The crew set up the camera and checked the flow. Ignited and burned for two minutes without trouble. Then the fan was turned off."
    assert outcomes.decide(note, "S2")["class"] == "burned"
    assert outcomes.decide(note, "S1")["status"] == "none"                     # not a candidate sentence: SI cannot invent evidence
    assert outcomes.decide(note, "S9")["status"] == "none"
    d = outcomes.decide(note, "none")
    assert d["status"] == "none" and d["review"] is True                       # candidates existed but SI said none: listed for review


def test_contradicting_notes_are_left_unlabelled():
    d = outcomes.decide("No ignition at the first attempt with the wire. Then it ignited and burned well after a retry.", "S2")
    assert d["status"] == "conflict" and d["class"] is None and d["review"] is True


def test_pointer_enum_is_limited_to_candidates(monkeypatch):
    seen = {}

    async def fake(http, url, model, system, user, schema, timeout, options=None):
        seen["enum"] = schema["properties"]["evidence"]["enum"]
        return {"evidence": "S2"}
    monkeypatch.setattr(ollama, "chat_json", fake)
    row = {"Test no.": "1", "material": "wax"}
    out = asyncio.run(outcomes.point(None, "http://x", "m", row, "The crew set up the camera and checked the flow. Ignited and burned for two minutes without trouble. Then the fan was turned off.", 5))
    assert seen["enum"] == ["S2", "none"] and out["class"] == "burned"


def test_si_failure_is_not_assessed_never_a_label(monkeypatch):
    async def boom(*a, **k):
        raise ollama.SIError("down")
    monkeypatch.setattr(ollama, "chat_json", boom)
    out = asyncio.run(outcomes.point(None, "http://x", "m", {}, "Ignited and burned for two minutes without trouble.", 5))
    assert out["status"] == "not assessed" and out["class"] is None


def _tests():
    return [{"row": 1, "values": {}}, {"row": 2, "values": {}}]


def _evidence(sha="abc"):
    return {"PSI-26": {"table": "T.csv", "sha256": sha, "rows": {"1": {"status": "evidence", "class": "burned", "id": "S1", "quote": "Burned.", "review": False},
                                                                  "2": {"status": "none", "class": None, "id": None, "quote": None, "review": False}}}}


def test_layer_attaches_with_the_document_flag_and_skips_the_rest():
    tests = _tests()
    assert outcome_layer.apply(tests, "PSI-26", "T.csv", "abc", _evidence()) == {"applied": 1, "stale": False}
    assert tests[0]["values"]["outcome"]["flag"] == "document_text" and tests[0]["outcome_quote"] == "Burned."
    assert "outcome" not in tests[1]["values"]
    assert sweeper._value(tests[0], "outcome") is None                          # table statistics cannot read it


def test_changed_table_gets_nothing_and_is_reported_stale():
    tests = _tests()
    assert outcome_layer.apply(tests, "PSI-26", "T.csv", "different", _evidence()) == {"applied": 0, "stale": True}
    assert all("outcome" not in t["values"] for t in tests)


def test_installed_evidence_is_pinned_to_the_table_and_quotes_are_verbatim():
    ev = json.loads((DATA / "outcome_evidence.json").read_text(encoding="utf-8"))["PSI-26"]
    catalog = load_catalog(DATA)
    table = next(t for t in catalog.manifest["investigations"]["PSI-26"]["tables"] if t["file"].endswith(ev["table"]))
    assert ev["sha256"] == table["sha256"]
    burn = [t for t in catalog.tests if t.get("outcome_kind") == "burn"]
    assert len(burn) == sum(1 for e in ev["rows"].values() if e["status"] == "evidence")
    with (DATA / "snapshot" / "tables" / "PSI-26" / ev["table"]).open(encoding="utf-8", newline="") as f:
        text = " ".join(" ".join(r.split()) for row in csv.reader(f) for r in row)
    assert all(" ".join(e["quote"].split()) in text for e in ev["rows"].values() if e["status"] == "evidence")


def test_document_layer_never_changes_the_table_families():
    catalog = load_catalog(DATA)
    saved = [dict(t["values"]) for t in catalog.tests]
    before = {f: sweeper.sweep(catalog, f, HABITAT) for f in ("droplet_end_state", "gas_ignition", "droplet_reignition")}
    doc = sweeper.sweep(catalog, "solid_burn", HABITAT)
    assert doc["layer"] == "document" and doc["tests"] == 53 and doc["skill"]["passes"] is False
    assert all(c["estimate"] is None for c in doc["cells"])                     # no model for document-derived outcomes
    assert all(t["source"] == "document" and t["quote"] for c in doc["cells"] for t in c["tests"])
    for f, r in before.items():
        assert r["layer"] == "table" and all(t["source"] == "table" for c in r["cells"] for t in c["tests"])
        assert (r["tests"], r["skill"].get("accuracy")) == (sweeper.sweep(catalog, f, HABITAT)["tests"], r["skill"].get("accuracy"))
    assert [dict(t["values"]) for t in catalog.tests] == saved
