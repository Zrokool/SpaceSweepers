"""Flame Sweeper: the grid, the intervals, the model and the rule that decides when an estimate may be shown."""

from pathlib import Path

import pytest

from app.analysis import sweeper
from app.analysis.habitats import HABITATS
from app.catalog import load_catalog

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(DATA)


def synthetic(rule, n=240):
    """Tests whose outcome follows `rule(o2, p)` exactly, spread over a grid."""
    rows = []
    for k in range(n):
        o2 = 0.12 + 0.22 * ((k * 7) % 23) / 22
        p = 0.5 + 2.5 * ((k * 11) % 19) / 18
        rows.append({"psi": "PSI-0", "file": "t.csv", "row": k + 2, "test_id": str(k), "o2": o2, "p_atm": p, "fuel": "x", "diluent": "nitrogen only",
                     "outcome": "completed" if rule(o2, p) else "extinguished", "diameter": None})
    return rows


def test_wilson_interval_widens_with_few_tests():
    lo, hi = sweeper.wilson(3, 3)
    assert lo > 0.4 and hi == 1.0                       # three of three is not certainty
    lo2, hi2 = sweeper.wilson(30, 30)
    assert lo2 > lo and sweeper.wilson(0, 0) == (0.0, 1.0)


def test_a_model_that_has_real_skill_passes_the_gate_and_one_that_does_not_fails():
    fam = sweeper.FAMILIES["droplet_end_state"]
    info, model = sweeper.skill(synthetic(lambda o, p: o > 0.23), fam)                  # outcome set by oxygen: learnable
    assert info["passes"] and model and info["accuracy"] > info["baseline"] + 0.05
    import random
    rng = random.Random(3)
    noise = synthetic(lambda o, p: False)
    for r in noise:
        r["outcome"] = "completed" if rng.random() < 0.5 else "extinguished"               # outcome unrelated to oxygen and pressure
    info, model = sweeper.skill(noise, fam)
    assert not info["passes"] and model is None and "only observed counts are shown" in info["reason"]


def test_too_few_tests_never_get_a_model():
    info, model = sweeper.skill(synthetic(lambda o, p: o > 0.23, n=30), sweeper.FAMILIES["droplet_end_state"])
    assert model is None and "at least 60 tests" in info["reason"]


def test_flex_beats_guessing_and_cfig_ignition_does_not(catalog):
    droplet = sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"])
    gas = sweeper.sweep(catalog, "gas_ignition", HABITATS["moon"])
    assert droplet["skill"]["passes"] and droplet["skill"]["accuracy"] > droplet["skill"]["baseline"] + 0.05
    assert not gas["skill"]["passes"] and not any(c["estimate"] for c in gas["cells"])     # observed counts only for CFI-G
    assert any(c["estimate"] for c in droplet["cells"])


def test_estimates_stay_inside_the_tested_range_and_beside_a_tested_cell(catalog):
    r = sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"])
    by = {(c["i"], c["j"]): c for c in r["cells"]}
    seen = [c for c in r["cells"] if c["state"] == "revealed"]
    lo_o, hi_o = min(c["o2"][0] for c in seen), max(c["o2"][1] for c in seen)
    lo_p, hi_p = min(c["p_atm"][0] for c in seen), max(c["p_atm"][1] for c in seen)
    for c in r["cells"]:
        if c["estimate"]:
            assert c["state"] == "fog" and lo_o <= c["o2"][0] and c["o2"][1] <= hi_o and lo_p <= c["p_atm"][0] and c["p_atm"][1] <= hi_p
            assert any(by.get((c["i"] + a, c["j"] + b), {}).get("state") == "revealed" for a in (-1, 0, 1) for b in (-1, 0, 1))
            assert 0 <= c["estimate"]["low"] <= c["estimate"]["share"] <= c["estimate"]["high"] <= 1


def test_every_test_is_in_exactly_one_cell_and_dropped_tests_are_counted(catalog):
    for family in sweeper.FAMILIES:
        r = sweeper.sweep(catalog, family, HABITATS["moon"])
        assert sum(c["n"] for c in r["cells"]) == r["tests"]
        assert sum(r["dropped"].values()) + r["tests"] <= len([t for t in catalog.tests if t.get("outcome_kind") == sweeper.FAMILIES[family]["outcome_kind"]])
    gas = sweeper.sweep(catalog, "gas_ignition", HABITATS["moon"])
    assert gas["dropped"] == {"oxygen is the burner stream, not the chamber": 154}        # inverse flames never sit on the room-air grid


def test_families_are_never_pooled(catalog):
    droplet = sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"])
    gas = sweeper.sweep(catalog, "gas_ignition", HABITATS["moon"])
    assert droplet["investigations"] == ["PSI-69"] and gas["investigations"] == ["PSI-159"]
    assert all(t["outcome"] in ("extinguished", "completed", "disrupted") for c in droplet["cells"] for t in c["tests"])
    assert all(t["outcome"] in ("ignited", "no_ignition", "flash") for c in gas["cells"] for t in c["tests"])


def test_a_flag_needs_three_tests_that_all_agree(catalog):
    r = sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"])
    for c in r["cells"]:
        if c["flag"]:
            assert c["modelled"] >= 3 and c["share"] == 1.0
        if c["state"] == "revealed" and c["modelled"] < 3:
            assert not c["flag"]


def test_patterns_are_computed_facts_with_numbers_that_match_the_tests(catalog):
    r = sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"])
    rows, _ = sweeper.collect(catalog, "droplet_end_state")
    p1 = next(p for p in r["patterns"] if p["id"] == "P1")
    above = [x for x in rows if round(x["o2"], 2) >= p1["numbers"]["o2"]]
    assert len(above) == p1["numbers"]["tests"] and all(x["outcome"] != "extinguished" for x in above)
    p4 = next(p for p in r["patterns"] if p["id"] == "P4")
    assert p4["numbers"]["tests"] == r["tests"]


def test_the_next_tests_are_untested_cells_beside_tested_ones(catalog):
    r = sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"])
    by = {(c["i"], c["j"]): c for c in r["cells"]}
    assert r["next"]
    for n in r["next"]:
        assert by[(n["i"], n["j"])]["state"] == "fog"
        assert any(by.get((n["i"] + a, n["j"] + b), {}).get("state") == "revealed" for a in (-1, 0, 1) for b in (-1, 0, 1) if a or b)


def test_filters_narrow_the_tests(catalog):
    heptane = sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"], fuel="heptane")
    he = sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"], diluent="helium")
    assert 0 < heptane["tests"] < 273 and 0 < he["tests"] < 273
    assert all(t["fuel"].lower() == "heptane" for c in heptane["cells"] for t in c["tests"])


def test_cfi_reignition_has_a_pressure_floor_and_its_skill_is_decided_by_the_gate(catalog):
    r = sweeper.sweep(catalog, "droplet_reignition", HABITATS["moon"])
    assert r["investigations"] == ["PSI-39"] and r["tests"] == 151 and r["dropped"] == {"no outcome recorded": 76}      # tests with no count are left out, never read as zero
    floor = next(p for p in r["patterns"] if p["id"] == "P5")
    assert floor["numbers"] == {"p_atm": 1.25, "below": 88, "above_yes": 37, "above": 63}                              # no test reignited at 1.25 atm or less
    assert r["skill"]["passes"] == (r["skill"]["accuracy"] >= r["skill"]["baseline"] + 0.05 and r["skill"]["auc"] >= 0.70)
    rows, _ = sweeper.collect(catalog, "droplet_reignition")
    assert sum(1 for x in rows if x["p_atm"] <= 1.25 and x["outcome"] == "reignited") == 0                            # the floor recomputed from the tests


def test_the_floor_fact_needs_a_clean_run_of_negatives_and_some_positives_above():
    fam = sweeper.FAMILIES["droplet_reignition"]
    base = {"psi": "P", "file": "t", "row": 1, "test_id": "x", "o2": 0.21, "fuel": "f", "diluent": "nitrogen only", "diameter": None}
    rows = [dict(base, p_atm=1.0, outcome="no_reignition") for _ in range(10)] + [dict(base, p_atm=3.0, outcome="reignited") for _ in range(4)]
    hab = {"o2": [0.3, 1], "pressure_psi": [4, 10]}
    assert any(p["id"] == "P5" for p in sweeper.patterns(rows, fam, hab))
    mixed = rows + [dict(base, p_atm=1.0, outcome="reignited")]                                                          # one positive at low pressure: no floor
    assert not any(p["id"] == "P5" for p in sweeper.patterns(mixed, fam, hab))
    assert not any(p["id"] == "P5" for p in sweeper.patterns(rows[:7], fam, hab))                                        # fewer than 8 low-pressure tests
