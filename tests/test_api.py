"""The dashboard API and the app's security headers, against the committed snapshot."""

import httpx

from tests.fakes import make_ollama


def test_security_headers_and_strict_csp(client):
    resp = client.get("/")
    assert resp.status_code == 200 and "SpaceSweepers" in resp.text
    csp = resp.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "unsafe-inline" not in csp and "unsafe-eval" not in csp
    assert "blob:" not in csp and "frame-ancestors 'none'" in csp and "connect-src 'self'" in csp
    assert resp.headers["x-content-type-options"] == "nosniff" and resp.headers["referrer-policy"] == "no-referrer"
    assert "<script>" not in resp.text and "onclick=" not in resp.text and " style=" not in resp.text


def test_unknown_hosts_are_refused(client):
    assert client.get("/api/meta", headers={"host": "evil.example"}).status_code == 400


def test_meta_and_ranked_investigations(client):
    meta = client.get("/api/meta").json()
    assert meta["counts"]["investigations"] == 26 and meta["counts"]["combustion"] == 24
    assert [h["key"] for h in meta["habitats"]] == ["iss", "moon", "eva"] and meta["default_habitat"] == "moon"
    data = client.get("/api/investigations", params={"habitat": "moon", "pillar": "detection"}).json()
    rows = data["investigations"]
    assert len(rows) == 26 and rows == sorted(rows, key=lambda r: -r["fit"]["total"])
    assert {"proximity", "fuel", "pillar", "data"} == set(rows[0]["fit"]["components"])
    by_id = {r["id"]: r for r in rows}
    assert by_id["PSI-102"]["fit"]["components"]["pillar"]["pillar"] == "detection"      # SAME is smoke detection
    assert by_id["PSI-181"]["fit"]["factor"] < 1 and "Not a combustion investigation" in by_id["PSI-181"]["fit"]["factor_reason"]
    assert by_id["PSI-117"]["uses_data_from"] == ["PSI-69"]


def test_habitat_validation(client):
    assert client.get("/api/investigations", params={"habitat": "venus"}).status_code == 404
    assert client.get("/api/investigations", params={"habitat": "custom"}).status_code == 422
    assert client.get("/api/investigations", params={"habitat": "custom", "o2_min": 0.5, "o2_max": 0.3, "p_min": 5, "p_max": 9}).status_code == 422
    ok = client.get("/api/envelope", params={"habitat": "custom", "o2_min": 0.3, "o2_max": 0.4, "p_min": 8, "p_max": 10.2})
    assert ok.status_code == 200 and ok.json()["habitat"]["key"] == "custom"
    assert client.get("/api/investigations", params={"pillar": "luck"}).status_code == 422


def test_detail_citation_and_bad_ids(client):
    inv = client.get("/api/investigations/PSI-159").json()
    assert inv["doi"] == "10.60555/cyt1-kh64" and inv["license"] == "CC0-1.0"
    assert "https://doi.org/10.60555/cyt1-kh64" in inv["cite"] and inv["stats"]["tests"] == 333                          # 154 inverse + 179 normal flames
    assert "email" not in str(inv).lower()
    assert client.get("/api/investigations/PSI-99999").status_code == 404
    for bad in ["nope", "PSI-1;DROP", "..%2F..%2Fetc"]:
        assert client.get(f"/api/investigations/{bad}").status_code in (404, 422)


def test_csv_export_carries_provenance(client):
    resp = client.get("/api/investigations/PSI-159/tests.csv")
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.splitlines()
    assert lines[0].startswith("investigation,doi,license,method_flag,source_file,row,test_id,o2_role,variable,raw_text,value,unit,quality_flag")
    pressure = next(line for line in lines if ",pressure_psi," in line and "oxidizer_stream" in line)       # an inverse-flame row
    assert "10.60555/cyt1-kh64" in pressure and "CC0-1.0" in pressure
    assert ",1.10,15.954151,psi,ok" in pressure          # raw text in bar, value in psi
    normal = next(line for line in lines if ",pressure_psi," in line and "Normal Flames" in line)
    assert ",ambient," in normal and "oxidizer_stream" not in normal             # normal flames: chamber oxygen


def test_compare_graph_sources_quality(client):
    assert client.post("/api/compare", json={"ids": ["PSI-69"]}).status_code == 422
    assert client.post("/api/compare", json={"ids": ["PSI-69", "PSI-4242"]}).status_code == 404
    assert client.post("/api/compare", json={"ids": ["PSI-69", "PSI-117"], "extra": 1}).status_code == 422
    assert client.post("/api/compare", json={"ids": ["PSI-69", "PSI-117"]}).status_code == 200
    assert len(client.get("/api/graph").json()["nodes"]) > 26
    sources = client.get("/api/sources").json()
    assert sources["sources"][0]["id"] == "psi" and len(sources["investigations"]) == 26
    assert all(s["url"].startswith("https://") for s in sources["sources"])
    assert len(client.get("/api/quality").json()["investigations"]) == 26


def test_si_status_with_and_without_ollama(make_client):
    assert make_client().get("/api/si/status").json()["available"] is False          # Ollama not running
    up = make_client(make_ollama([], models=("granite3.3:2b",))).get("/api/si/status").json()
    assert up == {"available": True, "model": "granite3.3:2b", "message": None}
    other = make_client(make_ollama([], models=("another-model:1b",))).get("/api/si/status").json()
    assert other["available"] is False and "ollama pull granite3.3:2b" in other["message"]


def test_the_app_uses_one_si_model():
    from app.config import Settings
    settings = Settings(_env_file=None)
    assert settings.si_model == "granite3.3:2b"
    assert not hasattr(settings, "si_fast_model") and not hasattr(settings, "si_batch_model")


def test_the_sweeper_api_returns_the_field_the_skill_check_and_what_to_test_next(client):
    r = client.get("/api/sweeper?family=droplet_end_state").json()
    assert [f["key"] for f in r["families"]] == ["droplet_end_state", "gas_ignition", "droplet_reignition", "solid_burn"] and r["tests"] > 200 and r["skill"]["passes"] is True
    assert r["axes"]["o2"]["n"] > 5 and r["cells"] and r["patterns"] and r["next"] and "definition" in r
    gas = client.get("/api/sweeper?family=gas_ignition").json()
    assert gas["skill"]["passes"] is False and not any(c["estimate"] for c in gas["cells"])
    assert client.get("/api/sweeper?family=nope").status_code == 404
    assert client.get("/api/sweeper?family=droplet_end_state&diluent=argon").status_code == 422
    he = client.get("/api/sweeper?family=droplet_end_state&diluent=helium").json()
    assert 0 < he["tests"] < r["tests"]
    moon = client.get("/api/sweeper?family=gas_ignition&habitat=moon").json()["habitat"]
    iss = client.get("/api/sweeper?family=gas_ignition&habitat=iss").json()["habitat"]
    assert moon["o2"] != iss["o2"]


def test_data_complexity_is_computed_from_the_snapshot(client):
    r = client.get("/api/data-complexity").json()
    by = {t["name"]: t for t in r["tier_b"]}
    assert by["SAFFIRE-I"]["has_pressure"] is False and by["SAFFIRE-I"]["on_charts"] == 0 and "pressure" in by["SAFFIRE-I"]["why_not"]
    assert by["BASS-II"]["has_oxygen"] is True and by["BASS-II"]["why_not"] == "No pressure column."
    assert by["BASS"]["on_charts"] == 121 and by["BASS"]["why_not"] is None
    layers = {x["name"]: x for x in r["layers"]}
    assert layers["PSI-117"]["analyzed"]["feasible"] is True and layers["CFI"]["raw"]["feasible"] is False


def test_the_examples_quoted_on_the_sources_page_are_really_in_the_tables():
    from pathlib import Path
    tables = Path(__file__).resolve().parent.parent / "data" / "snapshot" / "tables"
    text = {p.name: p.read_bytes().decode("utf-8-sig", errors="replace") for p in tables.rglob("*.csv")}
    assert "21.5 - 21.7" in text["PSI-98_Experimental table_SAFFIRE-1.csv"] and "~ 21.5" in text["PSI-98_Experimental table_SAFFIRE-1.csv"]
    assert "Insignificant" in text["PSI-99_Experimental table_SAFFIRE-2.csv"]
    assert "0.17; 0.21;0.25; 0.3" in text["PSI-68_Experimental table_Flex2.csv"]
    assert "% by volume" in text["PSI-26_Workbook table_BASS As Run.csv"]


def test_experiment_vs_simulation_series_match_the_stored_files(client):
    import csv
    from pathlib import Path
    r = client.get("/api/experiment-vs-simulation").json()
    assert r["psi"] == "PSI-117" and r["license"] == "CC0-1.0" and len(r["files"]) == 9
    fig7 = next(c for c in r["charts"] if c["figure"] == "Fig. 7")
    by = {s["name"]: s for s in fig7["series"]}
    assert by["Dext_HF_EXPT"]["kind"] == "experiment" and by["Dext_HF_model"]["kind"] == "simulation" and by["Dext_CF_ErrorBar+"]["kind"] == "bounds"
    path = Path(__file__).resolve().parent.parent / "data" / "snapshot" / "analyzed" / "PSI-117" / fig7["file"]
    rows = list(csv.reader(path.read_bytes().decode("utf-8-sig").splitlines()))
    assert by["Dext_HF_EXPT"]["points"][0] == [float(rows[1][0]), float(rows[1][1])] and by["Dext_CF_EXPT"]["points"][4] == [1.25, 0.38]
    assert fig7["reference"].startswith("https://doi.org/") and fig7["conditions"]["Fuel"] == "n-dodecane"


def test_analyzed_files_are_pinned_in_the_manifest_and_unchanged():
    import hashlib
    import json
    from pathlib import Path
    snap = Path(__file__).resolve().parent.parent / "data" / "snapshot"
    manifest = json.loads((snap / "manifest.json").read_text(encoding="utf-8"))
    files = [f for e in manifest["investigations"].values() for f in e.get("analyzed", [])]
    assert len(files) == 10 and all(f["license"] == "CC0-1.0" and f["doi"] for f in files)
    assert all(hashlib.sha256((snap / f["file"]).read_bytes()).hexdigest() == f["sha256"] for f in files)


def test_figure_specs_are_checked_against_the_files_headers(client):
    r = client.get("/api/figure-data/PSI-117").json()
    titles = [c["title"] for c in r["charts"]]
    assert len(r["charts"]) == 19 and not r["dropped"]
    assert "n-heptane oscillatory cool flame (simulation): peak temperature against time" in titles and "Radiance against time, 0.5 and 5 atm" in titles
    kinds = {s["kind"] for c in r["charts"] for s in c["series"]}
    assert kinds == {"experiment", "simulation", "bounds"}
    r142 = client.get("/api/figure-data/PSI-142").json()
    assert len(r142["charts"]) == 7 and {s["kind"] for c in r142["charts"] for s in c["series"]} == {"published"}      # the workbook never says measured or computed
    assert any("nC10" in d for d in r142["dropped"]) and any("nC7" in d for d in r142["dropped"])                        # header and values disagree: not drawn
    assert client.get("/api/figure-data/PSI-69").json()["charts"] == []


def test_a_figure_spec_that_no_longer_matches_its_file_is_dropped_not_guessed(tmp_path):
    from pathlib import Path
    from app.analysis import figures
    folder = tmp_path / "analyzed" / "PSI-X"
    folder.mkdir(parents=True)
    (folder / "f.csv").write_text("P,Dext\n1,2\n2,3\n", encoding="utf-8")
    spec = {"PSI-X": [{"file": "f.csv", "figure": "Fig. 1", "charts": [{"title": "t", "x": "P", "y": "D", "series": [
        {"name": "ok", "kind": "experiment", "x": 0, "y": 1, "expect": {0: "P", 1: "Dext"}},
        {"name": "wrong header", "kind": "experiment", "x": 0, "y": 1, "expect": {1: "Diameter"}}]}]}]}
    out = figures.charts_for("PSI-X", Path(tmp_path), spec)
    assert [s["name"] for s in out["charts"][0]["series"]] == ["ok"] and "Diameter" in out["dropped"][0]


def test_the_cfi_overlay_uses_real_cfi_tests_under_stated_conditions(client):
    import re
    from pathlib import Path
    r = client.get("/api/figure-data/PSI-117").json()
    o = next(c for c in r["charts"] if c["figure"] == "Fig. 7")["overlay"]
    assert o["tests"] == 38 and "C12H26" in o["conditions"] and {s["kind"] for s in o["series"]} == {"experiment-cfi"}
    table = (Path(__file__).resolve().parent.parent / "data" / "snapshot" / "tables" / "PSI-39" / "PSI-39_Workbook table_CFI Data Summary.csv").read_bytes().decode("utf-8-sig")
    assert all(re.search(rf"^{re.search(r'test (\d+[A-Za-z]?)', p[2]).group(1)},", table, re.M) for s in o["series"] for p in s["points"])      # each point is a real CFI test
