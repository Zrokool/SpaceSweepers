"""The static (GitHub Pages) copy: every answer the page can ask for exists as a file, and the files hold what the live app answers."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app import static_export as sx
from app.analysis import compare as compare_mod
from app.analysis.habitats import HABITATS

ROOT = Path(__file__).resolve().parent.parent
NODE = shutil.which("node")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    out = tmp_path_factory.mktemp("site") / "site"
    sx.build(out)
    return out


def run_node(tmp_path: Path, script: str, payload) -> list:
    """Run static/js/staticmap.js (the browser code) on `payload` and return its JSON answer."""
    module = tmp_path / "staticmap.mjs"
    module.write_text((ROOT / "static" / "js" / "staticmap.js").read_text(encoding="utf-8"), encoding="utf-8")
    code = f'import {{ staticFile, compareFromProfiles }} from "{module.as_uri()}";\nconst input = JSON.parse(process.argv[1]);\n{script}'
    done = subprocess.run([NODE, "--input-type=module", "-e", code, json.dumps(payload)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def ui_requests(catalog) -> list[tuple[str, dict]]:
    """Every request the pages can make in the static copy."""
    reqs = [(p, {}) for p in ("/api/meta", "/api/sources", "/api/quality", "/api/data-complexity", "/api/graph", "/api/si/status", "/api/compare-profiles", "/api/insights/demo")]
    reqs.append(("/api/investigations", {}))                                                     # compare.js and earth.js ask with no query
    for h in HABITATS:
        for pillar in (None, "prevention", "detection", "suppression"):
            reqs.append(("/api/investigations", {"habitat": h, **({"pillar": pillar} if pillar else {})}))
        for measured in ("true", "false"):
            reqs.append(("/api/envelope", {"habitat": h, "pillar": "detection", "measured_only": measured}))   # the pillar is ignored here
        for sel in sx.sweeper_selections():
            reqs.append(("/api/sweeper", {"habitat": h, **{k: v for k, v in sel.items() if v}}))
    for sel in sx.sweeper_selections():
        reqs.append(("/api/sweeper", {"habitat": "eva", "habitat_view": "off", **{k: v for k, v in sel.items() if v}}))
    for inv in catalog.ordered():
        reqs += [(f"/api/investigations/{inv['id']}", {}), (f"/api/investigations/{inv['id']}/tests.csv", {})]
    reqs += [(f"/api/figure-data/{i}", {}) for i in ("PSI-117", "PSI-142")]
    return reqs


def test_the_site_has_a_file_for_every_request_the_pages_make(site, catalog_and_library, tmp_path):
    catalog, _ = catalog_and_library
    reqs = ui_requests(catalog)
    assert all((site / sx.static_file(p, q)).is_file() for p, q in reqs), [sx.static_file(p, q) for p, q in reqs if not (site / sx.static_file(p, q)).is_file()][:5]
    if NODE:
        files = run_node(tmp_path, "console.log(JSON.stringify(input.map(([p, q]) => staticFile(p, q))));", reqs)
        assert files == [sx.static_file(p, q) for p, q in reqs]                                    # the browser and the exporter agree on every name
        assert all((site / f).is_file() for f in files)


def test_a_file_holds_what_the_live_app_answers(site, client):
    def same(path, params, rel_params=None):
        live = client.get(path, params=params).json()
        assert json.loads((site / sx.static_file(path, rel_params or params)).read_text(encoding="utf-8")) == live, (path, params)
    same("/api/investigations", {"habitat": "eva", "pillar": "detection"})
    same("/api/envelope", {"habitat": "iss", "measured_only": "true"})
    same("/api/sweeper", {"habitat": "moon", "family": "droplet_end_state", "fuel": "heptane", "diluent": "carbon dioxide"})
    same("/api/investigations/PSI-159", {})
    same("/api/sources", {})
    same("/api/sweeper", {"habitat": "eva", "habitat_view": "off", "family": "solid_burn"})
    off = json.loads((site / sx.static_file("/api/sweeper", {"habitat_view": "off", "family": "solid_burn"})).read_text(encoding="utf-8"))
    assert off["habitat"] is None and not any(p["kind"] == "habitat" for p in off["patterns"])           # the Habitat view off names no habitat
    assert (site / "api/investigations/PSI-10/tests.csv").read_text(encoding="utf-8").startswith("investigation,")


def test_the_browsers_comparison_equals_the_servers(site, catalog_and_library, tmp_path):
    if not NODE:
        pytest.skip("node is not installed")
    catalog, _ = catalog_and_library
    sets = [["PSI-26", "PSI-25"], ["PSI-69", "PSI-159", "PSI-39"], ["PSI-10", "PSI-23", "PSI-159", "PSI-69"], ["PSI-98", "PSI-100"], ["PSI-102", "PSI-101", "PSI-26"]]
    data = json.loads((site / "api/compare-profiles.json").read_text(encoding="utf-8"))
    got = run_node(tmp_path, "const d = input.data; console.log(JSON.stringify(input.sets.map((s) => compareFromProfiles(d, s))));", {"data": data, "sets": sets})
    assert got == [json.loads(json.dumps(compare_mod.compare(catalog, ids))) for ids in sets]


def test_the_page_uses_relative_paths_so_it_works_under_a_repository_address(site):
    html = (site / "index.html").read_text(encoding="utf-8")
    assert 'name="ss-static"' in html and '"/static/' not in html and '"static/js/app.js"' in html
    assert (site / ".nojekyll").exists() and (site / "static" / "js" / "staticmap.js").is_file()
    assert sum(f.stat().st_size for f in site.rglob("*") if f.is_file()) < 40_000_000                      # well inside Pages' limits


def test_the_demo_publishes_no_si_text_because_nimbus_cannot_check_meaning(site, tmp_path):
    """The generated explanations are kept in the repo but not published unless asked: some read wrongly against the patterns."""
    assert not list((site / "api").rglob("*explain*"))
    if sx.EXPLANATIONS.exists():
        stored = json.loads(sx.EXPLANATIONS.read_text(encoding="utf-8"))
        assert {"generated_at", "model", "spec_hash", "snapshot_fetched_at", "note", "explanations"} <= set(stored)
        assert len(stored["explanations"]) == len(sx.sweeper_selections())
        opted_in = tmp_path / "with"
        sx.build(opted_in, with_explanations=True)
        assert len(list((opted_in / "api").rglob("explain*"))) == len(stored["explanations"])


def test_the_files_the_demo_branch_serves_are_a_fresh_build(site):
    """GitHub Pages serves index.html, api/ and .nojekyll from the branch root. They must be what the exporter writes today."""
    assert (ROOT / ".nojekyll").exists(), "run: python -m app.static_export --publish"
    assert (ROOT / "index.html").read_bytes() == (site / "index.html").read_bytes(), "index.html is stale: run python -m app.static_export --publish"
    built = {p.relative_to(site / "api") for p in (site / "api").rglob("*") if p.is_file()}
    served = {p.relative_to(ROOT / "api") for p in (ROOT / "api").rglob("*") if p.is_file()}
    assert built == served, "api/ is stale: run python -m app.static_export --publish"
    assert [p for p in built if (site / "api" / p).read_bytes() != (ROOT / "api" / p).read_bytes()] == []


def test_the_static_si_status_says_the_demo_has_no_model(site):
    status = json.loads((site / "api" / "si" / "status.json").read_text(encoding="utf-8"))
    assert status["available"] is False and "static demo" in status["message"] and "Ollama" not in status["message"]


# ---------------------------------------------------------------- SI Insights on the demo: pre-generated answers, both modes
def demo_answers(site):
    return json.loads((site / "api" / "insights" / "demo.json").read_text(encoding="utf-8"))


def test_every_demo_use_case_has_a_code_written_answer_in_guided_and_in_expert(site):
    data = demo_answers(site)
    assert len(data["cases"]) == len(sx.INSIGHTS_CASES) >= 12
    for mode in ("guided", "expert"):
        for case in data["cases"]:
            entry = data["answers"][mode][sx.normalise_question(case["question"])]
            r = entry["report"]
            assert r["mode"] == "computed" and r["model"] is None and r["answer"], (mode, case["question"])   # no SI text anywhere
            assert not any(n.startswith("SI offline") for n in r["notes"])                                     # nothing that contradicts the demo banner
            assert r["run_id"].startswith("demo-") and all(s["cites"] and max(s["cites"]) <= len(r["sources"]) for s in r["answer"] if not s.get("note"))


def test_every_follow_up_chip_the_demo_offers_has_an_answer_and_the_safety_question_is_refused(site):
    data = demo_answers(site)
    for mode in ("guided", "expert"):
        followups = [(k, v) for k, v in data["answers"][mode].items() if "||" in k]
        assert followups and all(v["report"]["mode"] == "computed" for _, v in followups)
    refusal = data["answers"]["guided"][sx.normalise_question("Is there a fire in the cabin?")]["report"]["answer"][0]["text"]
    assert "cannot tell whether a fire is happening" in refusal and "no emergency instructions" in refusal


def test_the_demo_answers_are_the_same_every_time_they_are_generated():
    import asyncio
    first, second = (json.dumps(asyncio.run(sx.insights_demo()), sort_keys=True) for _ in range(2))
    assert first == second


def test_the_page_and_the_exporter_look_an_answer_up_by_the_same_key(tmp_path):
    if not NODE:
        pytest.skip("node is not installed")
    module = tmp_path / "staticmap.mjs"
    module.write_text((ROOT / "static" / "js" / "staticmap.js").read_text(encoding="utf-8"), encoding="utf-8")
    samples = ["What is a cool flame?", "  Is there   a FIRE in the cabin ? ", "Lowest oxygen where it burned...", "At 2 atm?! ", "plain"]
    code = f'import {{ normQuestion }} from "{module.as_uri()}"; console.log(JSON.stringify(JSON.parse(process.argv[1]).map(normQuestion)));'
    done = subprocess.run([NODE, "--input-type=module", "-e", code, json.dumps(samples)], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout) == [sx.normalise_question(s) for s in samples]


def test_the_demo_page_has_the_banner_and_puts_the_run_it_yourself_steps_after_the_chat():
    source = (ROOT / "static" / "js" / "views" / "insights.js").read_text(encoding="utf-8")
    assert "Demo Mode: SI Not Enabled" in source and "staticNotice" not in source
    render = source[source.index("export async function render"):]
    assert render.index("ui.insights = el(") < render.index("isStatic && runItYourself()")           # the steps are the last thing on the page
    assert "/api/insights/ask" in source                                                              # the live app still asks the server
