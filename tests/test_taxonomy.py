"""Table categorization: every table gets a family and a readiness tier, with the evidence it matched."""

from pathlib import Path

import pytest

from app.analysis.taxonomy import classify, load_taxonomy
from app.catalog import load_catalog

DATA = Path(__file__).resolve().parent.parent / "data"
TAXONOMY = load_taxonomy(DATA / "taxonomy.yaml")


@pytest.fixture(scope="module")
def tables():
    catalog = load_catalog(DATA)
    return {t["file"]: t | {"psi": i["id"]} for i in catalog.ordered() for t in i["tables"] if not t["status"].startswith("not downloaded")}


def find(tables, part):
    return next(t for f, t in tables.items() if part in f)


def test_every_table_has_a_family_a_tier_and_the_evidence_for_the_family(tables):
    assert len(tables) == 27                                       # 25 PSI tables plus the CFI and BASS workbook tables
    assert find(tables, "Experimental table_CFI.csv")["tier"] == "S" and find(tables, "Workbook table_CFI")["tier"] == "A"
    for t in tables.values():
        assert t["tier"] in "ABCDES" and t["tier_reason"] and t["family"] != "unclassified"
        assert t["family_evidence"], f"{t['file']} matched nothing"


def test_the_families_match_what_each_experiment_is(tables):
    expect = {"FLEX.csv": "droplet_combustion", "Flex2": "droplet_combustion", "CFI.csv": "droplet_combustion",
              "CFI-G_Normal": "gas_diffusion_flame", "Flame Design_Inverse": "gas_diffusion_flame", "ACME s-Flame": "gas_diffusion_flame",
              "Spice": "gas_diffusion_flame", "BASS-II": "solid_fuel_flammability", "SAFFIRE-2": "solid_fuel_flammability",
              "SAME-R": "smoke_aerosol", "DAFT": "smoke_aerosol", "STDCE-1.csv": "not_a_test_table", "PSI_181": "not_a_test_table"}
    for part, family in expect.items():
        assert find(tables, part)["family"] == family, part


def test_tiers_say_how_ready_each_table_is(tables):
    assert find(tables, "FLEX.csv")["tier"] == "A"                        # conditions and an end-state outcome for all 274 tests
    assert find(tables, "ACME BRE")["tier"] == "D" and "Flames Ignited" in find(tables, "ACME BRE")["tier_reason"]   # a count per test day
    assert find(tables, "Flex2")["tier"] == "D"                           # a test plan with several values per cell
    assert find(tables, "SAFFIRE-2")["tier"] == "B"                       # burn time and burn length, no categorical outcome
    assert find(tables, "BASS.csv")["tier"] == "E"                        # lists samples, no conditions
    assert find(tables, "STDCE-1.csv")["tier"] == "E"


def test_a_plan_table_is_never_called_outcome_ready():
    entry = {"status": "not mappable", "reason_code": "multi_value_cells", "reason": "several values per cell"}
    out = classify(TAXONOMY, ["Fuel", "Oxygen Mole Fraction", "Ambient Pressure (atm)"], {"title": "x", "approach": "droplet", "objective": ""}, entry)
    assert out["tier"] == "D" and out["family"] == "droplet_combustion"
