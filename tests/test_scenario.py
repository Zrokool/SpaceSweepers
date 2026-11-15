"""The scenario analyst: a researcher's or engineer's question answered from the tests by code. Ground truth is computed here by
plain loops over the harmonised tests, separately from app/analysis/queries.py."""

import asyncio
from pathlib import Path

import pytest

from app.analysis import queries as q
from app.analysis.sweeper import ATM_PSI, _value
from app.catalog import load_catalog
from app.insights import answers, concepts, pipeline, scenario
from app.insights.frame import reader_for
from app.insights.library import build_library
from tests.fakes import make_ollama_fn
from tests.test_insights import ask, events_of

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(DATA)


@pytest.fixture(scope="module")
def library(catalog):
    return build_library(catalog, DATA)


def card(catalog, question, structured=None):
    frame = reader_for(catalog).read(question)
    sc = scenario.read(question, frame, structured)
    return sc, (scenario.analyse(catalog, sc) or scenario.no_match(catalog, sc)) if sc else None


# ---------------------------------------------------------------- ground truth, by plain loops
def flex(fuel=None):
    return [t for t in load_catalog(DATA).tests if t["investigation"] == "PSI-69" and (not fuel or fuel in str(_value(t, "fuel")).lower())]


def test_lowest_oxygen_where_methanol_burned_matches_a_plain_loop(catalog):
    tests = [t for t in flex("methanol") if _value(t, "outcome")]
    burned = [_value(t, "o2_fraction") for t in tests if _value(t, "outcome") in ("completed", "disrupted")]
    below = [t for t in tests if _value(t, "o2_fraction") < min(burned)]
    sc, c = card(catalog, "What is the lowest oxygen concentration at which methanol droplets burned in FLEX?")
    assert sc.goal == "threshold" and sc.variable == "o2" and min(burned) == 0.18
    assert "18% oxygen" in c["headline"][0] and f"0 of {len(below)} tests burned" in c["headline"][1]
    assert "range" not in c["headline"][0]                                              # a range is never presented as a limit


def test_helium_carbon_dioxide_and_nitrogen_counts_match_a_plain_loop(catalog):
    counts = {}
    for t in flex():
        if not _value(t, "outcome") or t.get("o2_role") != "ambient" or _value(t, "o2_fraction") is None or _value(t, "pressure_psi") is None:
            continue                                       # the same rule the chart uses: the chamber's oxygen and a pressure are known
        gas = "helium" if (_value(t, "he_fraction") or 0) > 0 else "carbon dioxide" if (_value(t, "co2_fraction") or 0) > 0 else "nitrogen only"
        n, k = counts.get(gas, (0, 0))
        counts[gas] = (n + 1, k + (_value(t, "outcome") == "extinguished"))
    sc, c = card(catalog, "How does carbon dioxide compare with helium as a suppressant in FLEX?")
    assert sc.goal == "compare" and sc.compare_by == "diluent"
    for gas, (n, k) in counts.items():
        assert f"{gas}: the flame went out by itself in {k} of {n} tests" in " ".join(c["headline"])
    assert "did not change one gas at a time" in " ".join(c["headline"])                 # a comparison is never presented as controlled


def test_reignition_floor_matches_a_plain_loop(catalog):
    tests = [(_value(t, "pressure_psi") / ATM_PSI, _value(t, "outcome")) for t in load_catalog(DATA).tests
             if t["investigation"] == "PSI-39" and _value(t, "outcome") in ("reignited", "no_reignition")]
    low = min(p for p, o in tests if o == "reignited")
    below = [o for p, o in tests if p < low - 1e-9]
    sc, c = card(catalog, "At what pressure do reignitions of dodecane cool flames start to occur?")
    assert sc.variable == "p" and f"was {low:g} atm" in c["headline"][0]
    assert f"Below that, 0 of {len(below)} tests reignited" in c["headline"][1] and not any(o == "reignited" for o in below)


def test_nearest_tests_match_brute_force(catalog):
    rows = [(abs(_value(t, "o2_fraction") - 0.34) <= 0.05 and abs(_value(t, "pressure_psi") - 8.2) <= 2.0)
            for t in catalog.tests if t.get("o2_role") == "ambient" and _value(t, "o2_fraction") is not None and _value(t, "pressure_psi") is not None]
    sc, c = card(catalog, "We are designing a lunar habitat at 34% oxygen and 8.2 psi. Which tested conditions are closest and what happened?")
    assert sc.goal == "nearest" and f"{sum(rows)} of the {len(rows)} PSI tests" in c["headline"][0]
    first = c["table"]["rows"][0]
    assert first[-1].count(", row ") == 1 and (DATA / "snapshot" / "tables").exists()      # every test row names its file and row


def test_a_profile_accounts_for_every_test(catalog):
    sc, c = card(catalog, "Summarize how oxygen concentration affects flame extinction in microgravity based on PSI data.")
    assert sc.goal == "profile" and sum(int(r[1]) for r in c["table"]["rows"]) == 273


# ---------------------------------------------------------------- reading the question
@pytest.mark.parametrize("question,goal", [
    ("What is the lowest oxygen concentration at which methanol droplets burned in FLEX?", "threshold"),
    ("How does carbon dioxide compare with helium as a suppressant in FLEX?", "compare"),
    ("We are designing a cabin at 30% oxygen and 10 psi. What is the closest tested condition?", "nearest"),
    ("Which materials burned in BASS at oxygen above 21%?", "outcomes"),
    ("How does oxygen affect flame extinction?", "profile"),
])
def test_the_scenario_reader_finds_the_goal(catalog, question, goal):
    assert scenario.read(question, reader_for(catalog).read(question)).goal == goal


@pytest.mark.parametrize("question", ["What did FLEX find about extinction?", "Which investigations were simulations?", "How many ground studies reuse flight data?",
                                      "Is there a fire in the cabin?", "Compare BASS and BASS-II", "Which publications describe SPICE soot results?"])
def test_document_and_list_questions_are_left_to_the_existing_paths(catalog, question):
    sp = answers.build(reader_for(catalog).read(question), catalog, None)
    assert sp.analysis is None


def test_nothing_matches_says_which_condition_removes_the_tests(catalog):
    sc, c = card(catalog, "I need data on droplet extinction in helium-diluted atmospheres at 2 atm. What does PSI have?")
    text = " ".join(c["headline"])
    assert c["goal"] == "none" and "No mapped PSI test matches all of: helium" in text and "Without the pressure range condition" in text


# ---------------------------------------------------------------- the API and the scenario form
def test_a_scenario_from_the_form_is_validated_and_answered_by_code(make_client):
    ok = events_of(ask_scenario(make_client(), {"goal": "nearest", "fuel": "methanol", "o2_percent": 34, "pressure": 8.2, "pressure_unit": "psi"}))
    report = next(e["report"] for e in ok if e["type"] == "report")
    assert report["mode"] == "computed" and report["analysis"]["goal"] == "nearest" and len(report["analysis"]["table"]["rows"]) > 0
    atm = events_of(ask_scenario(make_client(), {"goal": "nearest", "o2_percent": 21, "pressure": 1, "pressure_unit": "atm"}))
    assert f"{ATM_PSI:.1f} psi" in next(e["report"] for e in atm if e["type"] == "report")["answer"][0]["text"]
    client = make_client()
    for bad in ({"goal": "nearest", "fuel": "unobtainium", "o2_percent": 30, "pressure": 10}, {"goal": "nearest", "o2_percent": 300, "pressure": 10},
                {"goal": "run code"}, {"goal": "nearest", "pressure": -1}):
        assert client.post("/api/insights/ask", json={"question": "Scenario", "history": [], "scenario": bad}).status_code in (404, 422)


def ask_scenario(client, scenario_input):
    return client.post("/api/insights/ask", json={"question": "Scenario: test", "history": [], "scenario": scenario_input})


def test_scenario_options_list_only_what_the_tests_contain(make_client):
    o = make_client().get("/api/insights/scenario-options").json()
    assert {f["name"] for f in o["fuels"]} >= {"methanol", "heptane", "n-dodecane"} and {d["name"] for d in o["diluents"]} == {"helium", "carbon dioxide", "nitrogen only"}
    assert o["tests"] == 1007 and o["o2_percent"] == [12.0, 40.0]


def test_a_scenario_answer_takes_no_model_call(make_client):
    calls = []
    handler = make_ollama_fn(lambda *a: calls.append(a) or {})
    events = events_of(ask(make_client(handler), "What is the lowest oxygen concentration at which methanol droplets burned in FLEX?"))
    assert next(e["report"] for e in events if e["type"] == "report")["mode"] == "computed" and not calls


# ---------------------------------------------------------------- concept questions: PSI's own words
@pytest.mark.parametrize("question,term", [("What is a cool flame and why does it matter for spacecraft fire safety?", "cool flame"), ("Define radiative extinction.", "radiative extinction"),
                                           ("Explain diffusion flames", "diffusion flames")])
def test_a_concept_question_finds_its_term(question, term):
    assert concepts.read_term(question) == term


@pytest.mark.parametrize("question", ["What did FLEX find about extinction?", "What is the lowest oxygen where it burned?", "What are the publications for SPICE?", "How many tests are there?"])
def test_other_questions_are_not_concept_questions(question):
    assert concepts.read_term(question) is None


def test_the_definition_is_psis_own_sentence_from_a_real_passage(library):
    cands = concepts.candidates(library, "cool flame")
    good = [c for c in cands if c.score >= concepts.MIN_SCORE and concepts.verify(c.sentence, "cool flame")]
    assert good and "cool flame is" in good[0].sentence.lower() and good[0].sentence in good[0].item.text      # word for word, from a passage we hold
    assert not concepts.verify("Representative images of a hot flame and a cool flame are presented.", "cool flame")


def test_the_pointer_can_only_choose_a_candidate_and_code_falls_back(library, make_client):
    seen = {}

    def respond(role, system, user, body):
        seen["enum"] = body["format"]["properties"]["evidence"]["enum"]
        return {"evidence": "D:PSI-0:not-a-candidate"}                                   # an invented id must be ignored (rule D-1)
    events = events_of(ask(make_client(make_ollama_fn(respond)), "What is a cool flame?"))
    report = next(e["report"] for e in events if e["type"] == "report")
    assert "cool flame is" in report["answer"][0]["text"].lower() and report["analysis"]["quote"]["where"]
    assert seen["enum"][-1] == "none" and all(x.startswith(("D:", "R:")) or x == "none" for x in seen["enum"])


def test_a_term_psi_never_defines_is_reported_as_such(library):
    c = concepts.card("zorbium plasma", None, [])
    assert "do not define" in c["headline"][0] and c["table"] is None


def test_the_concept_path_is_not_used_for_a_scenario_from_the_form(make_client):
    events = events_of(ask_scenario(make_client(), {"goal": "outcomes", "fuel": "methanol"}))
    assert next(e["report"] for e in events if e["type"] == "report")["analysis"]["goal"] == "outcomes"


def test_the_pipeline_exposes_the_concept_step():
    assert asyncio.iscoroutinefunction(pipeline.concept_special)


# ---------------------------------------------------------------- Guided mode: plain wording and follow-ups (Expert is unchanged)
def ask_with(client, question, **extra):
    return client.post("/api/insights/ask", json={"question": question, "history": [], **extra})


def report_of(resp):
    return next(e["report"] for e in events_of(resp) if e["type"] == "report")


FIRST = "What is the lowest oxygen concentration at which methanol droplets burned in FLEX?"


def test_expert_is_the_default_and_its_wording_is_unchanged(make_client):
    r = report_of(ask_with(make_client(), "Which investigations were simulations?"))
    assert r["answer"][0]["text"].startswith("Counted by code over the 26 investigations") and "checked-simulation" in r["answer"][0]["text"] and "()" not in r["answer"][0]["text"]
    assert r["analysis"] is None and r["scenario"] is None


def test_guided_wording_is_plain_and_the_names_are_still_in_the_sentence(make_client):
    r = report_of(ask_with(make_client(), "Which investigations were simulations?", audience="guided"))
    text = r["answer"][0]["text"]
    assert text.startswith("9 investigations labelled simulation:") and "counted by code" not in text.lower() and "PSI-117" in text and "ACME BRE" in text


def test_a_follow_up_keeps_the_goal_and_changes_only_what_the_user_changed(make_client):
    client = make_client()
    first = report_of(ask_with(client, FIRST, audience="guided"))
    assert first["scenario"]["fuel"] == "methanol" and first["scenario"]["goal"] == "threshold" and "heptane" in " ".join(f["label"] for f in first["followups"]).lower()
    second = report_of(ask_with(client, "What about heptane?", audience="guided", context=first["scenario"]))
    assert second["scenario"]["goal"] == "threshold" and second["scenario"]["fuel"] == "heptane" and second["analysis"]["goal"] == "threshold"
    assert "heptane" in second["answer"][0]["text"] and "Following on from your last question" in second["analysis"]["context_note"]
    third = report_of(ask_with(client, "And for carbon dioxide?", audience="guided", context=second["scenario"]))
    assert third["scenario"]["fuel"] == "heptane" and third["scenario"]["diluent"] == "carbon dioxide"


def test_the_follow_up_numbers_match_a_plain_loop(make_client, catalog):
    tests = [t for t in catalog.tests if t["investigation"] == "PSI-69" and "heptane" in str(_value(t, "fuel")).lower() and _value(t, "outcome")
             and t.get("o2_role") == "ambient" and _value(t, "o2_fraction") is not None and _value(t, "pressure_psi") is not None]
    low = min(_value(t, "o2_fraction") for t in tests if _value(t, "outcome") in ("completed", "disrupted"))
    first = report_of(ask_with(make_client(), FIRST, audience="guided"))
    r = report_of(ask_with(make_client(), "What about heptane?", audience="guided", context=first["scenario"]))
    assert f"{low * 100:.0f}% oxygen" in r["answer"][0]["text"]


def test_an_unrelated_question_inherits_nothing(make_client):
    ctx = report_of(ask_with(make_client(), FIRST, audience="guided"))["scenario"]
    r = report_of(ask_with(make_client(), "Which investigations were simulations?", audience="guided", context=ctx))
    assert r["scenario"] is None and r["answer"][0]["text"].startswith("9 investigations labelled simulation")
    r2 = report_of(ask_with(make_client(), "We are designing a cabin at 34% oxygen and 8.2 psi. What is the closest tested condition?", audience="guided", context=ctx))
    assert r2["scenario"]["goal"] == "nearest" and "inherit" not in str(r2["analysis"].get("context_note"))


def test_expert_ignores_a_context_so_its_behaviour_cannot_change(make_client):
    ctx = {"goal": "threshold", "target": "burn", "variable": "o2", "fuel": "methanol", "diluent": None, "o2": None, "p_psi": None}
    r = report_of(ask_with(make_client(), "What about heptane?", context=ctx))                # no audience: expert
    assert r["analysis"] is None or r["analysis"].get("context_note") is None


def test_a_bad_context_or_audience_is_refused(make_client):
    c = make_client()
    for bad in ({"goal": "run code"}, {"goal": "threshold", "fuel": "unobtainium"}, {"goal": "threshold", "o2": 5}, {"goal": "threshold", "p_psi": -1}, {"goal": "threshold", "extra": 1}):
        assert ask_with(c, "What about heptane?", audience="guided", context=bad).status_code in (404, 422)
    assert ask_with(c, "Hi", audience="beginner").status_code == 422


def test_guided_answers_still_take_no_model_call_for_scenarios(make_client):
    calls = []
    client = make_client(make_ollama_fn(lambda *a: calls.append(a) or {}))
    report_of(ask_with(client, FIRST, audience="guided"))
    assert not calls


def test_computed_ids_are_stable_between_runs(make_client):
    a = report_of(ask_with(make_client(), FIRST))["sources"][0]["id"]
    b = report_of(ask_with(make_client(), FIRST + " "))["sources"][0]["id"]
    assert a == b and a.startswith("C:scenario:threshold:") and len(a.split(":")[-1]) == 8
