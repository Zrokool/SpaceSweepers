"""The catalog built from the committed PSI snapshot: scope, lineage, tags, and the oxygen-role safeguard."""

import json
from pathlib import Path

import pytest

from app.analysis import compare, envelope, rank
from app.analysis.attributes import load_vocabulary, tag
from app.analysis.habitats import HABITATS, in_box
from app.catalog import load_catalog

DATA = Path(__file__).resolve().parent.parent / "data"


@pytest.fixture(scope="module")
def catalog():
    return load_catalog(DATA)


def test_scope_is_the_26_psi_search_results(catalog):
    assert len(catalog.investigations) == 26
    off_topic = sorted(i["id"] for i in catalog.ordered() if not i["is_combustion"])
    assert off_topic == ["PSI-108", "PSI-181"]          # listed by PSI's search, but not combustion research
    assert all("mentions combustion" in catalog.get(i)["match_reason"] for i in off_topic)


def test_no_contact_details_in_the_snapshot():
    import re
    email = re.compile(r"[a-z0-9._-]+@[a-z0-9-]+\.(edu|gov|com|org)", re.I)
    for path in (DATA / "snapshot").rglob("*.json"):
        assert not email.search(path.read_text()), path.name


def test_ground_studies_point_at_the_flight_data_they_use(catalog):
    uses = {i["id"]: i["uses_data_from"] for i in catalog.ordered() if i["project_type"] == "Ground" and i["is_combustion"]}
    assert uses == {"PSI-60": ["PSI-107"], "PSI-62": ["PSI-25", "PSI-26"], "PSI-115": ["PSI-102"],
                    "PSI-117": ["PSI-69"], "PSI-142": ["PSI-69"]}
    # PSI's links are one-way: FLEX lists nothing, yet two ground studies use its data.
    assert catalog.get("PSI-69")["related"] == []
    assert sorted(catalog.get("PSI-69")["data_used_by"]) == ["PSI-117", "PSI-142"]


def test_tags_carry_their_evidence_and_avoid_known_traps(catalog):
    vocabulary = load_vocabulary(DATA / "vocabulary.yaml")
    for inv in catalog.ordered():
        for f in inv["attributes"]["fuels"]:
            assert f["term"].lower() in f["quote"].lower() or f["quote"].endswith("…")
    # SAME measures smoke droplets, not fuel droplets: "droplet" alone must not tag a liquid fuel.
    assert "liquid" not in catalog.get("PSI-102")["attributes"]["fuel_classes"]
    # STDCE-1 used silicone oil as a test fluid in a fluid-physics experiment: not a solid fuel.
    assert catalog.get("PSI-108")["attributes"]["fuel_classes"] == []
    # "CIR" must match as a word, not inside "circular".
    assert tag({"approach": "A circular burner was used."}, vocabulary)["hardware"] == []
    assert [h["label"] for h in tag({"approach": "Tests ran in the CIR."}, vocabulary)["hardware"]] == ["CIR (Combustion Integrated Rack)"]
    assert catalog.get("PSI-20")["attributes"]["solid_emulation"]       # ACME BRE emulates burning solids


def test_burner_stream_oxygen_never_counts_as_habitat_air(catalog):
    """CFI-G inverse flames reach 85% oxygen in the burner stream. That is not Moon-base air."""
    moon = HABITATS["moon"]
    stats = catalog.get("PSI-159")["stats"]
    assert set(stats["o2_by_role"]) == {"ambient", "oxidizer_stream"} and stats["o2_by_role"]["oxidizer_stream"]["range"][1] == 0.85
    assert stats["o2_by_role"]["ambient"]["range"][1] < 0.41                      # normal flames: chamber oxygen never reaches the stream's 85%
    result = envelope.envelope(catalog, moon)
    ambient_inside = sum(1 for t in catalog.tests if t["o2_role"] == "ambient" and in_box(moon, rank._value(t, "o2_fraction"), rank._value(t, "pressure_psi")))
    assert result["gaps"]["in_box"] == ambient_inside > 0                           # only room-air oxygen counts as inside the box
    assert result["gaps"]["look_alike"] > 0 and "not counted" in result["gaps"]["look_alike_note"].lower()
    stream_only = [t for t in catalog.tests_for("PSI-159") if t["o2_role"] == "oxidizer_stream"]
    prox = rank.proximity(stream_only, moon)
    assert prox["score"] == 0.0 and "not the oxygen of the surrounding atmosphere" in prox["why"]


def test_tables_without_parsed_data_are_unknown_not_zero(catalog):
    """DAFT's table is downloaded but can't be mapped (it lists samples, not conditions): its condition match is unknown, never zero."""
    daft = catalog.get("PSI-47")
    assert daft["stats"] is None and daft["tables_status"].startswith("downloaded; not mappable: ")
    assert daft["tables"][0]["reason_code"] == "no_condition_columns"
    result = rank.score(daft, catalog.tests_for("PSI-47"), HABITATS["moon"], None)
    assert result["components"]["proximity"]["score"] is None
    caveat = envelope.envelope(catalog, HABITATS["moon"])["gaps"]["caveat"]
    assert caveat and "not 'never tested'" in caveat


def test_every_record_is_complete_with_its_doi(catalog):
    for inv in catalog.ordered():
        assert inv["record_complete"], inv["id"]
        assert inv["doi"] and inv["doi"].startswith("10.60555/"), inv["id"]
    assert catalog.get("PSI-10")["license"] is None                       # PSI records no license for PSI-10
    assert sum(1 for i in catalog.ordered() if i["license"] == "CC0-1.0") == 25
    cfig = catalog.get("PSI-159")
    assert cfig["proposal_title"].startswith("ISS: Collaborative Research") and str(cfig["version"]) == "1"
    assert cfig["file_inventory"]["Raw Data"]["files"] > 3000 and cfig["file_inventory"]["Raw Data"]["names"] == []
    assert sum(len(i["publications"]) for i in catalog.ordered()) == 367


def test_documents_are_read_or_listed_with_a_reason(catalog):
    docs = [d for i in catalog.ordered() for d in i["documents"]]
    read = [d for d in docs if d["status"] == "read"]
    assert len(read) == 47 and all(d["text_file"] and (DATA / "snapshot" / d["text_file"]).exists() for d in read)     # 52 before five workbooks became tables or were left out
    handled = {w["file"] for e in json.loads((DATA / "snapshot" / "manifest.json").read_text())["investigations"].values() for w in e.get("workbooks", [])}
    assert len(handled) == 5 and not handled & {d["file"] for d in docs}                  # a handled workbook is never also a document: nothing is stored twice
    assert all(d["status"].startswith("not read:") for d in docs if d not in read)
    assert all(d["bytes"] <= 5_000_000 for d in read)
    assert {d["folder"] for d in read} <= {"Reports", "Science Documents", "Analyzed Data"}   # ReadMe files can sit elsewhere


def test_proximity_counts_ambient_tests_in_and_near_the_box():
    def test(o2, psi, role="ambient"):
        return {"o2_role": role, "values": {"o2_fraction": {"value": o2, "flag": "ok"},
                                             "pressure_psi": {"value": psi, "flag": "ok"}}}
    moon = HABITATS["moon"]
    result = rank.proximity([test(0.34, 9.0), test(0.27, 11.0), test(0.21, 14.7), test(0.40, 8.0, "oxidizer_stream")], moon)
    assert (result["inside"], result["near"], result["tests"]) == (1, 1, 3)
    assert rank.proximity([], moon)["score"] is None
    flagged = test(0.34, 9.0)
    flagged["values"]["o2_fraction"]["flag"] = "implausible"       # a flagged value can't place a test in the box
    assert rank.proximity([flagged], moon)["inside"] == 0


def test_off_topic_investigations_rank_last(catalog):
    moon = HABITATS["moon"]
    totals = {i["id"]: rank.total(rank.score(i, catalog.tests_for(i["id"]), moon, None)) for i in catalog.ordered()}
    worst_two = sorted(totals, key=totals.get)[:2]
    assert sorted(worst_two) == ["PSI-108", "PSI-181"]


def test_compare_marks_shared_and_differing_attributes(catalog):
    result = compare.compare(catalog, ["PSI-69", "PSI-117"])
    rows = {r["attribute"]: r for r in result["attributes"]}
    assert rows["Type"]["all_same"] is False and rows["Fuel classes"]["shared"] == ["liquid"]
    assert rows["Uses flight data from"]["cells"] == {"PSI-69": [], "PSI-117": ["PSI-69"]}
    assert result["links"][0]["relation"] == "uses flight data from"
    graph = compare.graph(catalog)
    flight_edges = [e for e in graph["edges"] if e["relation"] == "uses flight data from"]
    assert len(flight_edges) == 6
    # A ground study that names a rig in its text didn't run on it.
    assert not any(e["relation"] == "ran on" and e["from"] == "PSI-60" for e in graph["edges"])


# ---------------------------------------------------------------- Rank data corrections
def test_an_emulator_is_tagged_with_the_gas_it_burns_not_the_solids_it_imitates(catalog):
    bre = catalog.get("PSI-20")["attributes"]
    assert bre["fuel_classes"] == ["gas"] and {f["term"] for f in bre["fuels"]} == {"CH4", "C2H4"}
    assert bre["solid_emulation"]
    fuel = rank.fuel(bre)
    assert fuel["score"] == 0.8 and "Emulates burning solids" in fuel["why"]          # credit for imitating solids, not for burning them


def test_fuels_are_also_read_from_the_test_tables_own_fuel_column(catalog):
    same = catalog.get("PSI-102")["attributes"]
    assert same["fuel_classes"] == ["solid"] and {"Teflon", "Kapton", "silicone rubber", "lampwick"} <= {f["term"] for f in same["fuels"]}
    teflon = next(f for f in same["fuels"] if f["term"] == "Teflon")
    assert teflon["field"] == "test table" and "Sample Material: Teflon (PSI-102_Experimental table_SAME.csv, row 2)" in teflon["quote"]
    assert catalog.get("PSI-25")["attributes"]["fuel_classes"] == ["solid"]
    assert catalog.get("PSI-108")["attributes"]["fuel_classes"] == []                # no fuel column, no fuel words: stays unknown


def test_a_ground_study_claims_no_hardware_or_sensors_of_its_own(catalog):
    for inv in catalog.ordered():
        if inv["project_type"] == "Ground":
            assert inv["attributes"]["hardware"] == [] and inv["attributes"]["sensors"] == [], inv["id"]
    assert catalog.get("PSI-60")["attributes"]["hardware"] == []                       # it only simulated ACME burner configurations
    assert catalog.get("PSI-69")["attributes"]["hardware"]                             # a flown investigation keeps its hardware


def test_data_richness_counts_the_data_we_hold_whether_or_not_its_columns_are_mapped(catalog):
    flex, same, cfig, ground = (rank.data_richness(catalog.get(i)) for i in ("PSI-69", "PSI-102", "PSI-159", "PSI-117"))
    assert catalog.get("PSI-69")["table_rows"] == 274 and flex["rows"] == 274 and flex["publications"] == 51
    assert flex["score"] == pytest.approx(0.4 + 0.3 + 0.0)                              # full rows and publications, no documents read
    assert cfig["rows"] == 333 and cfig["score"] == pytest.approx(0.4 + 0.3 * 0.2 + 0.3 * 0.2)   # both CFI-G tables count, not just the mapped one
    assert same["rows"] == 8 and same["score"] < flex["score"]
    assert ground["rows"] == 0 and "0 test-table rows" in ground["why"]
    assert "full marks at 100 rows" in flex["why"]


def test_rank_no_longer_lets_one_mapped_table_make_an_investigation_look_richest(catalog):
    totals = {i["id"]: rank.total(rank.score(i, catalog.tests_for(i["id"]), HABITATS["moon"], None)) for i in catalog.ordered()}
    assert totals["PSI-69"] > totals["PSI-159"]                                         # FLEX (274 rows, 51 publications) vs CFI-G
    # FLEX is now mapped, so its condition match is real. It leads because its tests, publications and condition data are real,
    # not because of a lucky single mapped table; the next investigations are the data-rich solid-fuel and smoke studies.
    ranked = sorted(totals, key=totals.get, reverse=True)
    assert ranked[0] == "PSI-69" and {"PSI-25", "PSI-101", "PSI-26", "PSI-102"} & set(ranked[1:6])
    assert totals["PSI-20"] < totals["PSI-25"]                                          # an emulator doesn't outrank the solids study it emulates for


def test_the_rank_api_reports_the_volumes_behind_each_score(client):
    rows = {r["id"]: r for r in client.get("/api/investigations").json()["investigations"]}
    assert (rows["PSI-69"]["table_rows"], rows["PSI-69"]["publications"], rows["PSI-69"]["documents_read"]) == (274, 51, 0)
    assert rows["PSI-102"]["documents_read"] == 3 and rows["PSI-117"]["table_rows"] == 0
    assert "274 test-table rows" in rows["PSI-69"]["fit"]["components"]["data"]["why"]


def test_psi117s_simulated_list_is_kept_apart_from_the_tests_and_shown_as_written(catalog):
    sim = catalog.get("PSI-117")["simulated_data"]
    assert len(sim["rows"]) == 9 and "not experiments" in sim["note"] and "stored unchanged in this snapshot" in sim["note"]
    assert [r["XN2"] for r in sim["rows"][:3]] == ["74", "85", "0.5"]                                              # nitrogen is written in different units: kept as written
    assert {"Data File", "Reference", "Figure"} <= set(sim["rows"][0]) and sim["rows"][0]["Reference"].startswith("https://doi.org/")
    assert catalog.tests_for("PSI-117") == [] and all(t["investigation"] != "PSI-117" for t in catalog.tests)      # never a test, never in a statistic
    assert catalog.get("PSI-69")["simulated_data"] is None


def test_the_simulation_strip_is_metadata_for_the_same_fuel_only(catalog):
    from app.analysis import sweeper
    from app.analysis.habitats import HABITATS
    r = sweeper.sweep(catalog, "droplet_reignition", HABITATS["moon"])
    kinds = {s["kind"] for s in r["simulations"]}
    assert r["simulations"] and kinds <= {"point", "range", "points"} and all("dodecane" in s["fuel"] for s in r["simulations"])
    assert not any(k in s for s in r["simulations"] for k in ("outcome", "result", "value"))                      # no simulated result values exist or are shown
    assert sweeper.sweep(catalog, "droplet_end_state", HABITATS["moon"])["simulations"] == []                    # not offered where it isn't about the same experiment
    assert sweeper._pressure_span("0.5 - 3.0") == ("range", [0.5, 3.0]) and sweeper._pressure_span("0.5 and 5.0") == ("points", [0.5, 5.0])
    assert sweeper._pressure_span("~4.5") == ("point", [4.5]) and sweeper._pressure_span("") is None
