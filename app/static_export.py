"""Export SpaceSweepers as a static site (for GitHub Pages): every answer the API gives is written to a file.

    python -m app.static_export --out _site              # build the site into a folder (to preview)
    python -m app.static_export --publish                # build it and write index.html, api/ and .nojekyll at the repo root
    python -m app.static_export --explain                # (needs Ollama) pre-compute the Flame Sweeper explanations

GitHub Pages has no server, so the Python app and the local SI model cannot run there. What can be pre-computed is: the
dashboard views (Rank, Envelope, Flame Sweeper, Compare, Fire Safety, References, detail panels) read the very same API as the
live app, called in-process, so the files hold exactly what the live app would answer. SI Insights (the chat) needs the model
and is replaced by a notice. The Flame Sweeper's SI explanation is left off the demo too: Nimbus checks a sentence's words and
numbers, not its meaning, and some pre-computed sentences read wrongly against the computed patterns. The generated explanations
stay in data/static_explanations.json (with the model, spec hash and time) but are only copied into the site with --with-explanations.

The request-to-file mapping lives in static/js/staticmap.js and below; a test runs both on the same inputs.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent

WANTED = {
    "/api/investigations": ["habitat", "pillar"],
    "/api/envelope": ["habitat", "measured_only"],
    "/api/sweeper": ["habitat", "habitat_view", "family", "fuel", "diluent"],
    "/api/sweeper/explain": ["family", "fuel", "diluent"],
}
DEFAULTS = {
    "/api/investigations": {"habitat": "moon"},
    "/api/envelope": {"habitat": "moon", "measured_only": "false"},
    "/api/sweeper": {"habitat": "moon", "habitat_view": "on", "family": "droplet_end_state"},
    "/api/sweeper/explain": {"family": "droplet_end_state"},
}
PILLARS = [None, "prevention", "detection", "suppression"]
FUEL_CHOICES = [None, "heptane", "methanol"]                                   # the Flame Sweeper's filters (static/js/views/sweeper.js)
DILUENT_CHOICES = [None, "nitrogen only", "helium", "carbon dioxide"]
EXPLANATIONS = ROOT / "data" / "static_explanations.json"


def _slug(v) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", str(v).strip().lower()))


def static_file(path: str, params: dict | None = None) -> str:
    """The file (relative to the site root) that answers one API request. Mirrors static/js/staticmap.js."""
    params = params or {}
    base = path.rstrip("/")
    if base.endswith(".csv"):
        return base[1:]
    wanted = WANTED.get(base)
    if wanted is None:
        return f"{base[1:]}.json"
    defaults = DEFAULTS.get(base, {})
    given = dict(defaults)
    for k in wanted:
        v = params.get(k)
        if v is not None and v != "" and v is not False:
            given[k] = "true" if v is True else str(v)
    if base == "/api/sweeper" and _slug(given.get("habitat_view", "")) == "off":
        given["habitat"] = defaults["habitat"]
    return f"{base[1:]}." + ".".join(f"{k}-{_slug(given[k])}" for k in wanted if k in given) + ".json"


def sweeper_selections() -> list[dict]:
    """Every Flame Sweeper selection the page can make: the droplet family with its fuel and gas filters, then the other families."""
    from app.analysis import sweeper as sweeper_mod
    out = [{"family": "droplet_end_state", "fuel": f, "diluent": d} for f in FUEL_CHOICES for d in DILUENT_CHOICES]
    out += [{"family": k, "fuel": None, "diluent": None} for k in sweeper_mod.FAMILIES if k != "droplet_end_state"]
    return out


def _write(out: Path, rel: str, content: bytes | str) -> None:
    target = out / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))


def _client(cache_dir: Path):
    """The live app, called in-process, with the network off: the same code answers as on a server."""
    from fastapi.testclient import TestClient

    from app.config import Settings, get_settings
    from app.deps import limiter
    from app.main import app

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("static export is offline", request=request)

    limiter.enabled = False
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, cache_dir=cache_dir, ollama_url="http://127.0.0.1:9")
    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(offline))
    return TestClient(app, base_url="http://localhost")


def build(out: Path, cache_dir: Path | None = None, with_explanations: bool = False) -> dict:
    """Write the whole site under `out` and return a short summary."""
    import tempfile

    from app.analysis import compare as compare_mod
    from app.analysis.habitats import HABITATS
    from app.catalog import load_catalog

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    cache = cache_dir or Path(tempfile.mkdtemp(prefix="ss-static-"))
    client = _client(cache)
    count = 0

    def fetch(path: str, params: dict | None = None, method: str = "get", json_body: dict | None = None, rel_params: dict | None = None):
        nonlocal count
        resp = client.request(method.upper(), path, params={k: v for k, v in (params or {}).items() if v not in (None, "")}, json=json_body)
        if resp.status_code != 200:
            raise SystemExit(f"{method.upper()} {path} {params} -> {resp.status_code}: {resp.text[:200]}")
        rel = static_file(path, rel_params if rel_params is not None else params)
        _write(out, rel, resp.content if path.endswith(".csv") else json.dumps(resp.json(), ensure_ascii=False, separators=(",", ":")))
        count += 1
        return resp

    habitats = list(HABITATS)
    meta = fetch("/api/meta").json()
    for path in ("/api/sources", "/api/quality", "/api/data-complexity", "/api/graph"):
        fetch(path)
    # The live app reports whether Ollama is running. A static page has no model at all, so it says that instead.
    from app.config import Settings
    _write(out, static_file("/api/si/status"), json.dumps({"available": False, "model": Settings(_env_file=None).si_model, "message":
           "This is the static demo, which has no SI model. The full app runs it locally."}, ensure_ascii=False, separators=(",", ":")))
    count += 1
    for habitat in habitats:
        for pillar in PILLARS:
            fetch("/api/investigations", {"habitat": habitat, "pillar": pillar})
        for measured in ("false", "true"):
            fetch("/api/envelope", {"habitat": habitat, "measured_only": measured})
        for sel in sweeper_selections():
            fetch("/api/sweeper", {"habitat": habitat, **sel})
    for sel in sweeper_selections():                                                   # the Habitat view off: no habitat in the answer
        fetch("/api/sweeper", {"habitat_view": "off", **sel})
    catalog = load_catalog(ROOT / "data")
    for inv in catalog.ordered():
        fetch(f"/api/investigations/{inv['id']}")
        fetch(f"/api/investigations/{inv['id']}/tests.csv")
        if client.get(f"/api/figure-data/{inv['id']}").status_code == 200:
            fetch(f"/api/figure-data/{inv['id']}")
    ids = [i["id"] for i in catalog.ordered()]
    _write(out, "api/compare-profiles.json", json.dumps({
        "profiles": {i: compare_mod.profile(catalog.investigations[i]) for i in ids},
        "names": {i: {"id": i, "name": catalog.investigations[i]["name"], "title": catalog.investigations[i]["title"]} for i in ids},
        "lineage": catalog.lineage}, ensure_ascii=False, separators=(",", ":")))
    count += 1
    explained = 0
    if with_explanations and EXPLANATIONS.exists():
        stored = json.loads(EXPLANATIONS.read_text(encoding="utf-8"))
        for rel, result in stored["explanations"].items():
            _write(out, rel, json.dumps({**result, "precomputed": {k: stored[k] for k in ("generated_at", "model", "spec_hash", "snapshot_fetched_at")}},
                                        ensure_ascii=False, separators=(",", ":")))
            explained += 1

    # the page and its assets, with paths that work under /<repo>/ as well as at a domain root
    shutil.copytree(ROOT / "static", out / "static")
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    html = html.replace('"/static/', '"static/').replace('<meta charset="utf-8">', '<meta charset="utf-8">\n  <meta name="ss-static" content="1">', 1)
    if 'name="ss-static"' not in html:
        raise SystemExit("static/index.html has no <meta charset=\"utf-8\"> to attach the static marker to")
    _write(out, "index.html", html)
    _write(out, ".nojekyll", "")
    return {"files": count + explained + 2, "explanations": explained, "snapshot": meta.get("snapshot", {}).get("fetched_at") if isinstance(meta, dict) else None}


async def precompute_explanations() -> dict:
    """Run Micro-Flame (SI, checked by Nimbus) for every Flame Sweeper selection and keep the checked results. Needs Ollama."""
    from app.analysis import sweeper as sweeper_mod
    from app.config import get_settings
    from app.insights import micro_flame
    from app.nimbus import spec
    from app.routes.insights import get_engine

    settings = get_settings()
    library, _, checker = get_engine(settings.data_dir)
    results = {}
    async with httpx.AsyncClient() as http:
        for n, sel in enumerate(sweeper_selections(), 1):
            result = sweeper_mod.sweep(library.catalog, sel["family"], None, sel["fuel"], sel["diluent"])
            explanation = (await micro_flame.explain(http, settings, library, checker, result)).as_dict()
            results[static_file("/api/sweeper/explain", sel)] = explanation
            print(f"{n:2} {sel['family']} {sel['fuel'] or '-'} {sel['diluent'] or '-'}: {len(explanation['answer'])} sentences kept, "
                  f"{len(explanation['removed'])} removed", flush=True)
    return {"generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": settings.si_model, "spec_hash": spec.spec_hash(),
            "snapshot_fetched_at": library.catalog.manifest.get("fetched_at"),
            "note": "Written by the local SI model from the Flame Sweeper's computed patterns and PSI passages, then checked sentence by sentence "
                    "by Nimbus. Computed without a habitat, so it does not depend on the habitat chosen on the page.",
            "explanations": results}


def publish(root: Path = ROOT) -> dict:
    """Build the site and write its generated files at the repository root, next to static/ (which the page already uses as is).

    GitHub Pages set to "Deploy from a branch" serves the branch root, so committing index.html, api/ and .nojekyll there is all the
    demo needs: no workflow and no environment settings.
    """
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ss-publish-") as tmp:
        site = Path(tmp) / "site"
        summary = build(site)
        if (root / "api").exists():
            shutil.rmtree(root / "api")
        shutil.copytree(site / "api", root / "api")
        for name in ("index.html", ".nojekyll"):
            shutil.copyfile(site / name, root / name)
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "_site", help="where to write the site (default _site/)")
    parser.add_argument("--publish", action="store_true", help="write index.html, api/ and .nojekyll at the repository root (what the demo branch serves)")
    parser.add_argument("--with-explanations", action="store_true", help="also publish the pre-computed Flame Sweeper explanations (off by default)")
    parser.add_argument("--explain", action="store_true", help="pre-compute the Flame Sweeper explanations with the local model (needs Ollama)")
    args = parser.parse_args(argv)
    if args.explain:
        data = asyncio.run(precompute_explanations())
        EXPLANATIONS.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"saved {EXPLANATIONS} ({len(data['explanations'])} explanations)")
        return 0
    if args.publish:
        summary = publish()
        print(f"published at the repository root: {summary['files']} files")
        return 0
    summary = build(args.out, with_explanations=args.with_explanations)
    print(f"static site written to {args.out}: {summary['files']} files, {summary['explanations']} pre-computed SI explanations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
