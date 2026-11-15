"""Micro-Flame: the agent that explains Flame Sweeper patterns. Spec, evidence, Nimbus rules, route and cache."""

import asyncio
import re
from pathlib import Path

import pytest

from app.catalog import load_catalog
from app.insights import micro_flame
from app.insights.frame import reader_for
from app.insights.library import Item
from app.insights.verify import Checker
from app.nimbus import runtime, spec
from tests.fakes import make_ollama_fn

DATA = Path(__file__).resolve().parent.parent / "data"
PATTERN = Item("C:sweeper:P1", "C", "-", 'At 0.34 oxygen or more, the outcome was "burned until the test ended" in all 9 tests.', "computed by code")
PASSAGE = Item("D:PSI-10:d6:p19:2", "D", "PSI-10", "Radiative extinction is unlikely in normal gravity because buoyancy increases with flame size.", "SRD, page 19")


@pytest.fixture(scope="module")
def checker():
    catalog = load_catalog(DATA)
    return Checker(catalog, reader_for(catalog))


@pytest.fixture(autouse=True)
def fresh_cache():
    micro_flame.CACHE.clear()


def find_e(user: str, needle: str) -> int:
    for line in user.split("\n"):
        if re.match(r"E\d+\. ", line) and needle in line:
            return int(line.split(".", 1)[0][1:])
    raise AssertionError(f"no evidence line with {needle!r}")


def ask(client, family="droplet_end_state"):
    return client.post("/api/sweeper/explain", json={"family": family})


# ------------------------------------------------------------------ the spec is the source of truth
def test_the_spec_holds_the_agents_configuration_and_the_skill_is_gone():
    agent = spec.agent(micro_flame.AGENT_FILE)
    assert agent.name == "micro-flame" and agent.meta["anchor_kind"] == "C" and agent.meta["max_passages"] == 6
    assert set(agent.meta["doc_queries"]) == {"droplet_end_state", "gas_ignition", "droplet_reignition", "solid_burn"}
    assert agent.output_schema["properties"]["sentences"]["maxItems"] == 3 and "academic tone" in agent.system_prompt
    assert not (Path(__file__).resolve().parent.parent / ".claude" / "skills" / "micro-flame").exists()      # one Micro-Flame, and it is the agent


# ------------------------------------------------------------------ Nimbus rules
def test_c_mech_a_named_mechanism_needs_a_psi_passage_that_names_it(checker):
    claim = "Flames at 0.34 oxygen or more burned on in all 9 tests, so radiative extinction did not stop them."
    assert "C-MECH" in [r for r, _ in checker.check(claim, [1], [PATTERN, PASSAGE])]                 # only a computed pattern is cited
    assert "C-MECH" not in [r for r, _ in checker.check("PSI documents discuss radiative extinction and buoyancy for these flames.", [2], [PATTERN, PASSAGE])]
    assert "C-MECH" in [r for r, _ in checker.check("PSI documents discuss Damköhler numbers here.", [2], [PATTERN, PASSAGE])]   # the passage doesn't name it


def test_c_anchor_is_only_enforced_when_asked_for(checker):
    text = "PSI documents discuss radiative extinction and buoyancy for these flames."
    assert "C-ANCHOR" in [r for r, _ in checker.check(text, [2], [PATTERN, PASSAGE], anchor_kind="C")]      # cites only a document
    assert "C-ANCHOR" not in [r for r, _ in checker.check(text, [2], [PATTERN, PASSAGE])]                   # the chat does not require it
    assert "C-ANCHOR" not in [r for r, _ in checker.check(text, [1, 2], [PATTERN, PASSAGE], anchor_kind="C")]


# ------------------------------------------------------------------ the agent end to end
def test_it_keeps_supported_sentences_and_removes_an_unsupported_mechanism(make_client):
    def respond(role, system, user, body):
        n = find_e(user, "At 0.34 oxygen or more")
        return {"sentences": [{"text": 'At 0.34 oxygen or more, the outcome was "burned until the test ended" in all 9 tests.', "cites": [n]},
                              {"text": "Radiative extinction explains why the other flames went out.", "cites": [n]}]}
    handler = make_ollama_fn(respond)
    r = ask(make_client(handler)).json()
    assert r["mode"] == "si" and len(r["answer"]) == 1 and r["answer"][0]["text"].startswith("At 0.34 oxygen or more")
    assert any("C-MECH" in x["rules"] for x in r["removed"]) and r["sources"][0]["computed"] is True
    body = handler.seen[0]["body"]
    prompt = body["messages"][-1]["content"]
    assert "computed by code" in prompt and "PSI document" in prompt                                  # computed patterns and PSI passages only
    assert body["format"]["properties"]["sentences"]["maxItems"] == 3 and body["options"]["temperature"] == 0


def test_a_sentence_that_cites_only_documents_is_removed_by_c_anchor(make_client):
    def respond(role, system, user, body):
        line = next(ln for ln in user.split("\n") if re.match(r"E\d+\. \[PSI document\]", ln))
        words = re.sub(r"^E\d+\. \[PSI document\] .*?page [^:]*: ", "", line).split()[:7]          # words from the passage itself, so only C-ANCHOR objects
        return {"sentences": [{"text": " ".join(words).rstrip(",;:") + ".", "cites": [int(re.match(r"E(\d+)\.", line).group(1))]},
                              {"text": 'At 0.34 oxygen or more, the outcome was "burned until the test ended" in all 9 tests.', "cites": [find_e(user, "At 0.34 oxygen or more")]}]}
    r = ask(make_client(make_ollama_fn(respond))).json()
    assert [a["text"][:12] for a in r["answer"]] == ["At 0.34 oxyg"] and any(x["rules"] == ["C-ANCHOR"] for x in r["removed"])


def test_the_same_selection_is_answered_from_the_cache(make_client):
    calls = []

    def respond(role, system, user, body):
        calls.append(role)
        return {"sentences": [{"text": 'At 0.34 oxygen or more, the outcome was "burned until the test ended" in all 9 tests.', "cites": [find_e(user, "At 0.34 oxygen or more")]}]}
    client = make_client(make_ollama_fn(respond))
    assert ask(client).json()["cached"] is False
    assert ask(client).json()["cached"] is True and len(calls) == 1                                    # the model wasn't asked twice


def test_without_si_nothing_is_invented_and_bad_input_is_rejected(make_client):
    r = ask(make_client(), "gas_ignition").json()                                                       # no Ollama behind the fake network
    assert r["mode"] == "offline" and r["answer"] == [] and "stand on their own" in r["notes"][0]
    assert ask(make_client(), "nope").status_code == 404
    assert make_client().post("/api/sweeper/explain", json={"family": "gas_ignition", "diluent": "argon"}).status_code == 422
    assert make_client().post("/api/insights/explain", json={"family": "gas_ignition"}).status_code in (404, 405)      # the old path is gone


def test_nothing_verified_means_no_explanation(make_client):
    r = ask(make_client(make_ollama_fn(lambda *a: {"sentences": [{"text": "A flame is a flame.", "cites": [1]}]}))).json()
    assert r["mode"] == "no_answer" and r["answer"] == [] and "no explanation is shown" in r["notes"][0]


# ------------------------------------------------------------------ the small parts
def test_the_cache_is_a_bounded_least_recently_used_store():
    cache = micro_flame.AnswerCache(size=2)
    for key in ("a", "b"):
        cache.put((key,), micro_flame.Explanation(mode="si"))
    assert cache.get(("a",)) is not None                    # touching a makes b the oldest
    cache.put(("c",), micro_flame.Explanation(mode="si"))
    assert cache.get(("b",)) is None and cache.get(("a",)) and cache.get(("c",))


def test_the_explanation_is_a_plain_json_shape():
    d = micro_flame.Explanation(mode="si", answer=[{"text": "x", "cites": [1]}]).as_dict()
    assert set(d) == {"mode", "answer", "sources", "removed", "notes", "model", "cached"} and d["cached"] is False


def test_one_model_call_at_a_time_is_shared_by_every_agent():
    async def check():
        return runtime.model_lock() is runtime.model_lock()
    assert asyncio.run(check())
