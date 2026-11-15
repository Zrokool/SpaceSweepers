"""Pillar evidence: candidates found by code, a pointer checked by rules, scores from a quote plus measured results."""

import asyncio
from pathlib import Path

import httpx
import pytest

from app.analysis import pillars as scoring
from app.analysis.attributes import load_vocabulary
from app.catalog import load_catalog
from app.nimbus import pillars, spec
from tests.fakes import make_ollama

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(DATA)


@pytest.fixture(scope="module")
def vocab():
    return load_vocabulary(DATA / "vocabulary.yaml")


def cue(text, pillar, vocab, field="objective"):
    return pillars.is_candidate(field, text, vocab["pillar_cues"][pillar], vocab["pillar_cue_exclusions"])


def test_spec_and_schema_load():
    agent = spec.agent(pillars.AGENT_FILE)
    assert agent.name == "pillar-pointer" and list(agent.output_schema["properties"]) == list(pillars.PILLARS)
    assert "ONE sentence" in agent.system_prompt


def test_cue_words_only_find_candidates_and_the_rules_screen_them(vocab):
    assert cue("Determine the flammability limits of spacecraft materials in low gravity.", "prevention", vocab)
    assert not cue("Determine the effects of nozzle diameter on the smoke points of flames.", "detection", vocab)        # smoke point = soot, not detection
    assert not cue("Thermopile detectors measured flame radiant emissions.", "detection", vocab)                       # an instrument, not fire detection
    assert not cue("The Fire Prevention, Detection, and Suppression program plan allows re-evaluation.", "suppression", vocab, "impacts")
    assert not cue("Study the Burning and Suppression of Solids experiment hardware.", "suppression", vocab)
    assert not cue("Evaluate the impact of fuel dilution with nitrogen on soot formation.", "suppression", vocab)       # dilution is not a cue
    assert not cue("The work does not address flame extinction in any way.", "suppression", vocab)                     # negated
    assert not cue("Results are based on earlier flame extinction studies.", "suppression", vocab)                     # about other work
    assert cue("Results improve fire detection systems.", "detection", vocab, "impacts")                              # an Impacts sentence needs no purpose verb


def test_the_approach_is_offered_only_when_nothing_better_fits(catalog, vocab):
    for inv in catalog.ordered():
        ids = pillars.numbered(inv)
        for pillar, found in pillars.candidates(inv, vocab).items():
            fields = {ids[s][0] for s in found}
            assert fields == {"approach"} or "approach" not in fields, (inv["id"], pillar)


def test_non_combustion_work_gets_no_pillars(catalog, vocab):
    result = asyncio.run(_label(catalog.get("PSI-108"), vocab, []))
    assert all(result[p]["status"] == "not applicable" for p in pillars.PILLARS)


async def _label(inv, vocab, answers):
    handler = make_ollama(answers)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        out = await pillars.label_one(http, "http://127.0.0.1:11434", "granite3.3:2b", inv, vocab, 30)
    out["_seen"] = handler.seen
    return out


def test_si_can_only_point_at_a_candidate_and_an_invented_id_is_ignored(catalog, vocab):
    inv = catalog.get("PSI-47")
    cands = pillars.candidates(inv, vocab)
    real = cands["detection"][0]
    result = asyncio.run(_label(inv, vocab, [{"prevention": "A99", "detection": real, "suppression": "none"}]))
    assert result["detection"]["status"] == "evidence" and result["detection"]["id"] == real
    assert result["detection"]["quote"] == pillars.numbered(inv)[real][1]                 # copied from the record by code
    assert result["prevention"]["status"] == "none"                                       # A99 is not a candidate
    props = result["_seen"][0]["format"]["properties"]
    assert props["detection"]["enum"] == [*cands["detection"], "none"] and props["suppression"]["enum"] == ["none"]


def test_si_saying_none_while_candidates_exist_is_listed_for_review_not_labelled(catalog, vocab):
    inv = catalog.get("PSI-69")
    result = asyncio.run(_label(inv, vocab, [{"prevention": "none", "detection": "none", "suppression": "none"}]))
    assert all(result[p]["status"] == "none" for p in pillars.PILLARS) and result["review"]


def test_a_failed_model_call_is_not_assessed_not_none(catalog, vocab):
    result = asyncio.run(_label(catalog.get("PSI-47"), vocab, ["not json", "still not json"]))
    assert all(result[p]["status"] == "not assessed" for p in pillars.PILLARS) and "didn't answer" in result["reason"]


# ------------------------------------------------------------------ scores from evidence and measured results
def test_data_links_come_from_measured_results(catalog):
    rules = catalog.vocabulary["pillar_data_links"]
    flex = scoring.data_links(catalog.get("PSI-69"), catalog.tests_for("PSI-69"), rules)
    assert flex["suppression"]["tests"] == 186 and "went out by itself" in flex["suppression"]["why"]
    cfig = scoring.data_links(catalog.get("PSI-159"), catalog.tests_for("PSI-159"), rules)
    assert cfig["prevention"]["tests"] == 263 and "suppression" not in cfig
    same = scoring.data_links(catalog.get("PSI-102"), catalog.tests_for("PSI-102"), rules)
    assert "detection" in same and "rows" in same["detection"]
    assert scoring.data_links(catalog.get("PSI-47"), [], rules) == {}                    # DAFT's table lists samples: no measured results


def test_points_and_statuses(catalog):
    inv = catalog.get("PSI-47")
    quote = pillars.numbered(inv)["I1"][1]
    entry = {"detection": {"status": "evidence", "field": "impacts", "quote": quote}, "prevention": {"status": "none"}, "suppression": {"status": "none"}}
    link = {"detection": {"why": "x", "rows": 2, "file": "t.csv"}, "prevention": {"why": "y", "rows": 2, "file": "t.csv"}}
    out = scoring.assemble(inv, entry, None, link)
    assert out["detection"]["points"] == 5 and out["detection"]["score"] == 1.0 and out["detection"]["status"] == "evidence"     # impacts 3 + data 2
    assert out["prevention"]["status"] == "data only" and out["prevention"]["score"] == 0.4 and out["prevention"]["quote"] is None
    assert out["suppression"]["status"] == "none" and out["suppression"]["score"] == 0.0
    assert scoring.assemble(inv, None, None, {})["detection"]["status"] == "not assessed" and scoring.assemble(inv, None, None, {})["detection"]["score"] is None


def test_a_quote_that_left_the_record_is_stale_and_a_team_entry_wins(catalog):
    inv = catalog.get("PSI-47")
    gone = {"detection": {"status": "evidence", "field": "impacts", "quote": "This sentence is not in the record."}}
    assert scoring.assemble(inv, gone, None, {})["detection"]["status"] == "stale"
    team = {"detection": {"field": "objective", "quote": pillars.numbered(inv)["O1"][1]}}
    out = scoring.assemble(inv, gone, team, {})["detection"]
    assert out["status"] == "evidence" and out["provenance"] == "team-confirmed" and out["points"] == 2


def test_describe_is_one_plain_sentence():
    ev = {"status": "evidence", "field": "impacts", "quote": "Better detectors.", "data_link": {"why": "N tests"}}
    assert scoring.describe(ev) == "Research Impacts: “Better detectors.” Measured results: N tests."
    assert scoring.describe({"status": "data only", "data_link": {"why": "N rows"}}).startswith("No sentence in the record states it.")
    assert "Not applicable" in scoring.describe({"status": "not applicable"})
