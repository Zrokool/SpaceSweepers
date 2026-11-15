"""Variable registry, table mapper rules (M-1 to M-5) and the ledger. Real PSI tables; no model."""

import json
import shutil
from pathlib import Path

import pytest

from app.catalog import load_catalog, read_table
from app.nimbus import tables
from app.psi.harmonise import harmonise_table
from app.psi.ledger import REASONS, STATUSES, load_registry, resolve
from app.psi.units import PSI_PER

DATA = Path(__file__).resolve().parent.parent / "data"
SNAP = DATA / "snapshot"
REGISTRY = load_registry(DATA / "variables.yaml")


def load(psi, part):
    path = next((SNAP / "tables" / psi).glob(f"*{part}*"))
    header, rows = read_table(SNAP, {"file": f"tables/{psi}/{path.name}"})
    return header, rows, path


def verify(psi, part, **pointers):
    header, rows, _ = load(psi, part)
    return tables.verify(header, rows, {k: "none" for k in REGISTRY} | pointers, REGISTRY)


def test_registry_units_all_have_a_tested_conversion():
    for key in ("pressure_psi",):
        assert set(REGISTRY[key]["units"]) <= set(PSI_PER)
    assert REGISTRY["o2_fraction"]["canonical_unit"] == "mole_fraction" and REGISTRY["o2_fraction"]["needs_ambient"]


def test_candidates_come_from_the_registry_not_from_si():
    header, _, _ = load("PSI-69", "FLEX")
    found = tables.candidates(header, REGISTRY)
    assert found["pressure_psi"] == ["Ambient pressure; mmHg"] and found["test_id"] == ["FLEX Test #"]


def test_flex_table_maps_with_units_from_its_headers_and_evidence():
    r = verify("PSI-69", "FLEX", test_id="FLEX Test #", fuel="Fuel", o2_fraction="O initial ambient composition; mole fraction",
               pressure_psi="Ambient pressure; mmHg", burn_time_s="Burn time; s")
    assert r["mapped"] and r["o2_role"] == "ambient" and r["reason_code"] is None
    assert r["columns"]["pressure_psi"]["unit"] == "mmhg"
    first = r["evidence"]["pressure_psi"][0]
    assert first["raw"] == "757.7" and 14.6 < first["value"] < 14.7            # converted by code, shown with its raw cell
    header, rows, path = load("PSI-69", "FLEX")
    mapping = {"investigation": "PSI-69", "label": "FLEX", "o2_role": "ambient", "test_id": "FLEX Test #",
               "columns": {k: v for k, v in r["columns"].items() if k != "test_id"}}
    out = harmonise_table(path.read_bytes(), mapping, path.name)
    assert len(out["tests"]) == 274


def test_a_unit_stated_in_each_cell_counts_but_a_header_and_cells_without_one_never_do():
    r = verify("PSI-39", "CFI", test_id="Flex Number", pressure_psi="Pressure", o2_fraction="Oxygen")
    assert r["columns"]["pressure_psi"]["unit"] == "atm" and r["columns"]["pressure_psi"]["unit_in_cell"] is True    # "1 atm"
    assert r["evidence"]["pressure_psi"][0]["raw"] == "1 atm" and r["evidence"]["pressure_psi"][0]["value"] == 14.695949
    assert "o2_fraction" not in r["columns"]                                    # "Oxygen" holds 0.21 with no unit and no "ambient" anywhere
    assert any(c["rule"] == "M-2" and c["variable"] == "o2_fraction" and not c["ok"] for c in r["checks"])


def test_oxygen_is_not_mapped_when_the_table_never_says_ambient():
    r = verify("PSI-10", "Inverse", test_id="Test", pressure_psi="pmean (atm)", o2_fraction="XO2")
    assert "o2_fraction" not in r["columns"]


def test_test_plan_tables_with_several_values_per_cell_are_not_mappable():
    r = verify("PSI-68", "Flex2", test_id="Sample (Fuel Type)", pressure_psi="Ambient Pressure (atm)", o2_fraction="Oxygen Mole Fraction")
    assert not r["mapped"] and r["reason_code"] == "multi_value_cells"


def test_invented_headers_are_rejected():
    r = verify("PSI-69", "FLEX", test_id="Test number", pressure_psi="Ambient pressure; mmHg")
    assert not r["mapped"] and any(c["rule"] == "M-1" for c in r["checks"])


def test_test_id_must_be_unique():
    r = verify("PSI-69", "FLEX", test_id="Fuel", pressure_psi="Ambient pressure; mmHg")
    assert not r["mapped"] and r["reason_code"] == "test_id_not_unique"


def test_a_table_with_no_condition_columns_says_so():
    r = verify("PSI-47", "DAFT", test_id="Session Name")
    assert not r["mapped"] and r["reason_code"] == "no_condition_columns"


# ------------------------------------------------------------------ the ledger and stale mappings
def entry(sha, status="mapped"):
    return {"investigation": "PSI-69", "sha256": sha, "status": status, "provenance": "rules", "reason_code": "multi_value_cells",
            "mapping": {"file": "t.csv", "test_id": "id", "columns": {}}}


def test_a_mapping_applies_only_to_the_exact_table_it_was_made_for():
    ok = resolve("t.csv", "aaa", {}, {"t.csv": entry("aaa")})
    assert ok["status"] == "mapped" and ok["mapping"]["investigation"] == "PSI-69"
    stale = resolve("t.csv", "bbb", {}, {"t.csv": entry("aaa")})                   # the table changed after it was mapped
    assert stale["status"] == "stale" and stale["mapping"] is None and "data refresh needed" in stale["reason"]
    assert resolve("t.csv", "aaa", {}, {})["status"] == "no mapping yet"
    assert resolve("t.csv", "aaa", {}, {"t.csv": entry("aaa", "not mappable")})["status"] == "not mappable"


def test_hand_mappings_win_and_are_pinned_to_their_table():
    hand = {"t.csv": {"file": "t.csv", "sha256": "aaa"}}
    assert resolve("t.csv", "aaa", hand, {"t.csv": entry("zzz", "not mappable")})["source"] == "hand-reviewed"
    assert resolve("t.csv", "changed", hand, {})["status"] == "stale"


def test_every_downloaded_table_gets_an_explicit_status():
    """No table is skipped silently: mapped, stale, not mappable or no mapping yet, each with its reason."""
    catalog = load_catalog(DATA)
    entries = [t for i in catalog.ordered() for t in i["tables"]]
    manifest_tables = sum(len(v["tables"]) for v in catalog.manifest["investigations"].values())
    downloaded = [t for t in entries if not t["status"].startswith("not downloaded")]
    assert len(downloaded) == manifest_tables
    for t in downloaded:
        assert t["status"] in STATUSES + ("parsed",)
        if t["status"] != "parsed":
            assert t["reason_code"] in REASONS and t["reason"]


def test_changing_a_table_blocks_its_mapping_in_the_catalog(tmp_path):
    work = tmp_path / "data"
    shutil.copytree(DATA, work)
    manifest_path = work / "snapshot" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    tables_159 = manifest["investigations"]["PSI-159"]["tables"]
    inverse = next(t for t in tables_159 if "Inverse" in t["file"])
    inverse["sha256"] = "0" * 64                                                    # as if PSI published a different file
    manifest_path.write_text(json.dumps(manifest))
    catalog = load_catalog(work)
    inv = catalog.get("PSI-159")
    assert [t["status"] for t in inv["tables"] if "Inverse" in t["file"]] == ["stale"]
    assert len(catalog.tests_for("PSI-159")) == 179                                 # only the unchanged Normal Flames table still counts
    assert inv["stats"] is not None and "Inverse" not in " ".join(t["file"] for t in inv["tables"] if t["status"] == "parsed")


def test_a_hand_mapping_whose_document_quote_disappears_is_blocked(tmp_path):
    work = tmp_path / "data"
    shutil.copytree(DATA, work)
    doc = work / "snapshot" / "docs" / "PSI-159" / "PSI-159_Reports_FinalRpt_ACME.CFI-G.pdf.txt"
    doc.write_text(doc.read_text(encoding="utf-8", errors="replace").replace("normal flames in which the fuel flowed", "XXXX"), encoding="utf-8")
    catalog = load_catalog(work)
    normal = next(t for t in catalog.get("PSI-159")["tables"] if "Normal" in t["file"])
    assert normal["status"] == "stale" and normal["reason_code"] == "evidence_missing" and "data refresh needed" in normal["reason"]


# ------------------------------------------------------------------ outcomes, diluents, composition
FLEX = dict(test_id="FLEX Test #", fuel="Fuel", o2_fraction="O initial ambient composition; mole fraction",
            n2_fraction="N initial ambient composition; mole fraction", co2_fraction="CO initial ambient composition; mole fraction",
            he_fraction="He initial ambient composition; mole fraction", pressure_psi="Ambient pressure; mmHg",
            droplet_diameter_mm="Droplet initial diameter; mm", end_state="Test end")


def test_flex_maps_its_outcome_diluents_and_droplet_size_and_proves_the_gases_are_one_mixture():
    r = verify("PSI-69", "FLEX", **FLEX)
    assert r["mapped"] and r["outcome_kind"] == "end_state"
    assert r["columns"]["outcome"]["values"] == {"extinction": "extinguished", "disruption": "disrupted", "completion": "completed"}
    assert {"he_fraction", "co2_fraction", "n2_fraction", "droplet_diameter_mm"} <= set(r["columns"])
    assert r["composition"]["rows"] == 274 and r["composition"]["within"] == 274                 # O + N + "CO" + He = 1 in every row
    assert any(c["rule"] == "M-8" and c["ok"] for c in r["checks"])


def test_an_outcome_value_the_registry_does_not_define_is_never_mapped():
    header = ["Test", "Fuel", "Pressure (atm)", "XO2 (ambient)", "Hot ignition"]
    rows = [(i + 2, [f"T{i}", "propane", "1", "0.21", v]) for i, v in enumerate(["Yes", "No", "flash", "maybe", "yes"])]
    r = tables.verify(header, rows, {k: "none" for k in REGISTRY} | {"test_id": "Test", "ignition": "Hot ignition", "pressure_psi": "Pressure (atm)"}, REGISTRY)
    assert "outcome" not in r["columns"] and any(c["rule"] == "M-6" and c["code"] == "unknown_outcome_values" and "maybe" in c["detail"] for c in r["checks"])
    assert r["mapped"]                                                         # the conditions still map; only the outcome waits for review
    rows[3] = (5, ["T3", "propane", "1", "0.21", "No"])
    r = tables.verify(header, rows, {k: "none" for k in REGISTRY} | {"test_id": "Test", "ignition": "Hot ignition", "pressure_psi": "Pressure (atm)"}, REGISTRY)
    assert r["columns"]["outcome"]["values"] == {"yes": "ignited", "no": "no_ignition", "flash": "flash"} and r["outcome_kind"] == "ignition"


def test_gas_columns_that_do_not_add_up_are_not_trusted():
    header = ["Test", "O2 mole fraction (ambient)", "N2 mole fraction", "He mole fraction"]
    rows = [(i + 2, [f"T{i}", "0.21", "0.40", "0.10"]) for i in range(10)]            # sums to 0.71
    r = tables.verify(header, rows, {k: "none" for k in REGISTRY} | {"test_id": "Test", "o2_fraction": header[1], "n2_fraction": header[2], "he_fraction": header[3]}, REGISTRY)
    assert any(c["rule"] == "M-8" and not c["ok"] for c in r["checks"])
    assert "he_fraction" not in r["columns"] and "n2_fraction" not in r["columns"] and "o2_fraction" in r["columns"]


def test_outcomes_travel_with_the_harmonised_tests():
    catalog = load_catalog(DATA)
    inverse = [t for t in catalog.tests if t["investigation"] == "PSI-159"]
    assert inverse and all(t["outcome_kind"] in ("ignition", None) for t in inverse)
