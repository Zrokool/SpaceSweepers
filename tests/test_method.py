"""Method labels: SI only points at sentences; fixed rules decide Experimental, Simulation, both or Not classified.
Cases are real PSI records."""

import asyncio
from pathlib import Path

import httpx
import pytest

from app.catalog import load_catalog
from app.nimbus import method, spec
from tests.fakes import make_ollama

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(DATA)


def sid(inv, needle):
    return next(k for k, (_, s) in method.numbered(inv).items() if needle.lower() in s.lower())


def decide(inv, physical="none", model="none"):
    return method.decide(inv, {"physical_evidence": physical, "model_evidence": model}, method.numbered(inv))


def test_spec_is_loaded_from_markdown_and_asks_only_for_pointers():
    agent = spec.agent("10-investigator.md")
    assert agent.name == "investigator" and "You do not decide labels" in agent.system_prompt
    assert list(agent.output_schema["properties"]) == ["physical_evidence", "model_evidence"]
    assert len(spec.spec_hash()) == 16


def test_old_labels_are_gone():
    assert method.FLAGS == ("experimental", "simulation", "both", "unverified")


def test_saffire_simulating_a_fabric_is_not_a_simulation(catalog):
    """Keyword matching would call Saffire-I a simulation: its sample was 'simulating a large piece of fabric'."""
    saffire = catalog.get("PSI-98")
    wrong = decide(saffire, model=sid(saffire, "simulating a large piece"))
    assert wrong["simulation"] is None and wrong["labels"] == ["Experimental"]       # flown, so Experimental from PSI's own type and platform
    assert any("no modelling word" in c["detail"] for c in wrong["checks"])
    right = decide(saffire, physical=sid(saffire, "experiments was performed"))
    assert (right["flag"], right["status"], right["measured"]) == ("experimental", "verified", True)
    assert right["experimental"]["quote"].startswith("The Saffire-1 experiments was performed")      # word for word, typo and all


def test_a_flown_investigation_is_experimental_from_psi_even_if_si_points_at_nothing(catalog):
    flex = catalog.get("PSI-69")
    result = decide(flex)
    assert result["labels"] == ["Experimental"] and result["experimental"]["quote"] is None
    assert "flown on International Space Station" in result["experimental"]["basis"]


def test_ground_cfd_study_is_simulation_only_and_flight_data_is_not_its_own_test(catalog):
    cfd = catalog.get("PSI-117")
    openfoam, reused = sid(cfd, "OpenFOAM"), sid(cfd, "use flight data obtained from PSI")
    ok = decide(cfd, model=openfoam)
    assert (ok["flag"], ok["labels"], ok["measured"]) == ("simulation", ["Simulation"], False)
    assert "OpenFOAM" in ok["simulation"]["quote"] and ok["simulation"]["field"] == "approach"
    for physical in (openfoam, reused):          # neither the model sentence nor the flight-data sentence shows an own test
        wrong = decide(cfd, physical=physical, model=openfoam)
        assert wrong["labels"] == ["Simulation"] and wrong["experimental"] is None
    assert any("builds on flight data from PSI-69" in c["detail"] or "modelling" in c["detail"] for c in wrong["checks"])


def test_a_simulation_sentence_cannot_prove_a_physical_test(catalog):
    smoke = catalog.get("PSI-115")
    simulated = sid(smoke, "simulated")
    result = decide(smoke, physical=simulated, model=simulated)
    assert result["labels"] == ["Simulation"] and result["experimental"] is None


def test_two_separate_labels_when_both_are_shown(catalog):
    acme = catalog.get("PSI-159")
    result = decide(acme, physical=sid(acme, "Perform spherical diffusion"), model=sid(acme, "advanced CFD"))
    assert (result["flag"], result["labels"]) == ("both", ["Experimental", "Simulation"])
    assert result["experimental"]["quote"] and result["simulation"]["quote"]          # each label has its own evidence


def test_a_sentence_that_only_validates_models_goes_to_review_not_to_a_label(catalog):
    slice_ = catalog.get("PSI-106")
    result = decide(slice_, model=sid(slice_, "Validate numerical models"))
    assert result["labels"] == ["Experimental"] and result["simulation"] is None
    assert result["review"] and "only says models are validated or compared" in result["review"][0]


def test_si_missing_an_own_model_sentence_is_listed_for_review_not_labelled(catalog):
    cfd = catalog.get("PSI-117")
    result = decide(cfd)
    assert result["flag"] == "unverified" and result["labels"] == []
    assert result["review"] and "SI pointed at no sentence" in result["review"][0]
    assert "may describe" in result["reason"]


def test_invented_sentence_ids_are_rejected(catalog):
    flex = catalog.get("PSI-69")
    result = decide(flex, physical="A999", model="Z1")
    assert not all(c["ok"] for c in result["checks"]) and result["simulation"] is None


def flag_with(answers, inv):
    handler = make_ollama(answers)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await method.label_one(http, "http://127.0.0.1:11434", "granite3.3:2b", inv, 30)
    return asyncio.run(go()), handler.seen


def test_model_can_only_point_at_real_sentences_or_none(catalog):
    cfd = catalog.get("PSI-117")
    result, seen = flag_with([{"physical_evidence": "none", "model_evidence": sid(cfd, "OpenFOAM")}], cfd)
    assert result["flag"] == "simulation" and result["model"] == "granite3.3:2b"
    props = seen[0]["format"]["properties"]
    assert props["physical_evidence"]["enum"] == [*method.numbered(cfd), "none"] == props["model_evidence"]["enum"]
    assert seen[0]["options"]["temperature"] == 0
    prompt = seen[0]["messages"][1]["content"]
    assert "Type: Ground Investigation" in prompt and "A1: OpenFOAM was used" in prompt


def test_a_failed_pointer_gets_one_second_chance_through_the_same_checks(catalog):
    smoke = catalog.get("PSI-115")
    simulated = sid(smoke, "simulated")
    result, seen = flag_with([{"physical_evidence": simulated, "model_evidence": "none"},
                              {"physical_evidence": "none", "model_evidence": simulated}], smoke)
    assert result["flag"] == "simulation" and len(seen) == 2
    assert "A check failed" in seen[1]["messages"][1]["content"]
    # Two wrong answers can't talk their way past the rules.
    result, seen = flag_with([{"physical_evidence": simulated, "model_evidence": "none"}] * 2, smoke)
    assert result["labels"] == [] and len(seen) == 2


def test_invalid_json_or_no_model_is_not_assessed(catalog):
    result, seen = flag_with(["not json", "still not json"], catalog.get("PSI-98"))
    assert (result["flag"], result["status"]) == ("unverified", "not assessed") and len(seen) == 2
