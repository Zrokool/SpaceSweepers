"""The dashboard's read-only API. Everything here is computed from the PSI snapshot; no SI."""

from __future__ import annotations

import csv
import io
from collections import Counter
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from app.analysis import compare as compare_mod
from app.analysis import complexity
from app.analysis import extinction
from app.analysis import envelope as envelope_mod
from app.analysis import rank
from app.analysis import sweeper as sweeper_mod
from app.analysis.habitats import DEFAULT_HABITAT, HABITATS
from app.catalog import Catalog, get_catalog
from app.config import Settings, get_settings
from app.deps import get_http, limiter
from app.psi import ledger
from app.psi.client import COLLECTION_URL
from app.si import ollama

router = APIRouter(prefix="/api", tags=["dashboard"])
Pillar = Literal["prevention", "detection", "suppression"]
PSI_ID = r"^PSI-\d{1,5}$"


def catalog_dep(settings: Annotated[Settings, Depends(get_settings)]) -> Catalog:
    return get_catalog(settings.data_dir)


Cat = Annotated[Catalog, Depends(catalog_dep)]


def habitat_dep(
    habitat: Annotated[str, Query(max_length=12)] = DEFAULT_HABITAT,
    o2_min: Annotated[float | None, Query(ge=0, le=1)] = None,
    o2_max: Annotated[float | None, Query(ge=0, le=1)] = None,
    p_min: Annotated[float | None, Query(ge=0, le=200)] = None,
    p_max: Annotated[float | None, Query(ge=0, le=200)] = None,
) -> dict:
    """A named habitat, or `habitat=custom` with its own oxygen and pressure limits."""
    if habitat == "custom":
        if None in (o2_min, o2_max, p_min, p_max) or o2_min > o2_max or p_min > p_max:
            raise HTTPException(422, "custom habitat needs o2_min ≤ o2_max and p_min ≤ p_max")
        return {"key": "custom", "label": "Custom atmosphere",
                "summary": f"{o2_min:.0%}–{o2_max:.0%} O₂ · {p_min:g}–{p_max:g} psi",
                "o2": [o2_min, o2_max], "pressure_psi": [p_min, p_max], "basis": "Set by you."}
    if habitat not in HABITATS:
        raise HTTPException(404, f"unknown habitat {habitat!r}")
    return {"key": habitat, **HABITATS[habitat]}


Habitat = Annotated[dict, Depends(habitat_dep)]


def _summary(inv: dict) -> dict:
    """The fields list views need."""
    keys = ("id", "name", "title", "acronym", "project_type", "research_area", "is_combustion", "match_reason",
            "platform", "doi", "license", "landing_url", "record_complete", "tables_status",
            "uses_data_from", "data_used_by")
    a = inv["attributes"]
    return {**{k: inv[k] for k in keys},
            "method": {k: inv["method"].get(k) for k in ("flag", "labels", "status", "experimental", "simulation", "review", "reason", "model")},
            "fuel_classes": a["fuel_classes"], "solid_emulation": bool(a["solid_emulation"]),
            "hardware": [h["label"] for h in a["hardware"]],
            "pillars": {p: {"status": v["status"], "score": v["score"]} for p, v in inv["pillars"].items()},
            "tests": inv["stats"]["tests"] if inv["stats"] else None, "table_rows": inv["table_rows"],
            "publications": len(inv["publications"]), "documents_read": sum(1 for d in inv["documents"] if d["status"] == "read")}


def _table_summary(invs: list[dict], taxonomy: dict | None = None) -> dict:
    """How every downloaded test table was handled, computed from the catalog. `stale` lists tables whose mapping is blocked."""
    rows = [(i, t) for i in invs for t in i["tables"] if not t["status"].startswith("not downloaded")]
    return {"total": len(rows),
            "by_status": dict(Counter(t["status"] for _, t in rows)),
            "by_reason": dict(Counter(t["reason_code"] for _, t in rows if t.get("reason_code"))),
            "reason_text": {t["reason_code"]: t["reason"] for _, t in rows if t.get("reason_code")},
            "stale": [{"psi": i["id"], "name": i["name"], "file": t["file"]} for i, t in rows if t["status"] == "stale"],
            "by_tier": dict(sorted(Counter(t.get("tier") for _, t in rows).items())),
            "tiers": (taxonomy or {}).get("tiers", {}),
            "readiness": [{"psi": i["id"], "name": i["name"], "file": t["file"], "family": t.get("family_label"), "tier": t.get("tier"),
                           "why": t.get("tier_reason"), "evidence": t.get("family_evidence", []), "tests": t.get("tests", 0)} for i, t in rows]}


@router.get("/meta")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def meta(request: Request, catalog: Cat) -> dict:
    invs = catalog.ordered()
    return {
        "snapshot": {"fetched_at": catalog.manifest["fetched_at"], "source": COLLECTION_URL,
                     "documents": {"read": sum(1 for i in invs for d in i["documents"] if d["status"] == "read"),
                                   "pages": sum(d.get("pages") or 0 for i in invs for d in i["documents"] if d["status"] == "read"),
                                   "not_read": sum(1 for i in invs for d in i["documents"] if d["status"] != "read")},
                     "query": catalog.manifest.get("query"),
                     "record_sources": dict(Counter(i["record_source"] for i in invs))},
        "counts": {"investigations": len(invs),
                   "combustion": sum(i["is_combustion"] for i in invs),
                   "by_type": dict(Counter(i["project_type"] for i in invs)),
                   "by_method": dict(Counter(i["method"]["flag"] for i in invs)),
                   "tests": len(catalog.tests),
                   "investigations_with_tests": sum(1 for i in invs if i["stats"]),
                   "complete_records": sum(i["record_complete"] for i in invs)},
        "tables": _table_summary(invs, catalog.taxonomy),
        "habitats": [{"key": k, **v} for k, v in HABITATS.items()],
        "default_habitat": DEFAULT_HABITAT,
        "pillars": ["prevention", "detection", "suppression"],
        "weights": rank.DEFAULT_WEIGHTS,
    }


@router.get("/investigations")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def investigations(request: Request, catalog: Cat, habitat: Habitat, pillar: Pillar | None = None) -> dict:
    """Every investigation with its Mission Fit components. The browser applies the weights."""
    rows = []
    for inv in catalog.ordered():
        result = rank.score(inv, catalog.tests_for(inv["id"]), habitat, pillar)
        rows.append({**_summary(inv), "fit": {**result, "total": rank.total(result), "ceiling": rank.ceiling(result)}})
    rows.sort(key=lambda r: (-r["fit"]["total"], r["id"]))
    results = {r["id"]: r["fit"] for r in rows}
    three = tuple(k for k in rank.DEFAULT_WEIGHTS if k != "proximity")
    return {"habitat": habitat, "pillar": pillar, "weights": rank.DEFAULT_WEIGHTS, "investigations": rows, "method": rank.method(),
            "stability": {"all": rank.stability(results), "without_proximity": rank.stability(results, three)}}


@router.get("/investigations/{psi_id}")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def investigation(request: Request, catalog: Cat, psi_id: Annotated[str, Field(pattern=PSI_ID)]) -> dict:
    inv = catalog.get(psi_id)
    if inv is None:
        raise HTTPException(404, f"{psi_id} is not one of the investigations in the snapshot")
    names = {i["id"]: i["name"] for i in catalog.ordered()}
    cite = (f"{inv['title']}. NASA Physical Sciences Informatics (PSI), {inv['id']}. "
            + (f"https://doi.org/{inv['doi']}" if inv["doi"] else inv["landing_url"]))
    return {**inv, "names": {i: names.get(i, i) for i in inv["related"] + inv["related_in"]}, "cite": cite}


@router.get("/investigations/{psi_id}/tests.csv")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def tests_csv(request: Request, catalog: Cat, psi_id: Annotated[str, Field(pattern=PSI_ID)]) -> Response:
    """Harmonised tests with full provenance: raw text, parsed value, unit, flag, file, row, DOI, license."""
    inv = catalog.get(psi_id)
    if inv is None:
        raise HTTPException(404, f"{psi_id} is not one of the investigations in the snapshot")
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["investigation", "doi", "license", "method_flag", "source_file", "row", "test_id", "o2_role",
                     "variable", "raw_text", "value", "unit", "quality_flag", "range_low", "range_high"])
    for t in catalog.tests_for(psi_id):
        for v in t["values"].values():
            writer.writerow([psi_id, inv["doi"] or "", inv["license"] or "", inv["method"]["flag"], t["file"], t["row"],
                             t["test_id"], t["o2_role"] or "", v["variable"], v["raw"], "" if v["value"] is None else v["value"],
                             v["unit"] or "", v["flag"], "" if v["lo"] is None else v["lo"], "" if v["hi"] is None else v["hi"]])
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{psi_id}_harmonised_tests.csv"'})


class CompareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ids: list[Annotated[str, Field(pattern=PSI_ID)]] = Field(min_length=2, max_length=4)


@router.post("/compare")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def compare(request: Request, catalog: Cat, body: CompareRequest) -> dict:
    ids = list(dict.fromkeys(body.ids))
    unknown = [i for i in ids if catalog.get(i) is None]
    if unknown or len(ids) < 2:
        raise HTTPException(404 if unknown else 422, f"unknown investigations: {unknown}" if unknown
                            else "pick at least two different investigations")
    return compare_mod.compare(catalog, ids)


@router.get("/graph")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def graph(request: Request, catalog: Cat) -> dict:
    return compare_mod.graph(catalog)


@router.get("/envelope")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def envelope(request: Request, catalog: Cat, habitat: Habitat, measured_only: bool = False) -> dict:
    return {"habitat": habitat, "habitats": [{"key": k, **v} for k, v in HABITATS.items()],
            **envelope_mod.envelope(catalog, habitat, measured_only)}


_sweeper_cache: dict = {}


@router.get("/sweeper")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def sweeper(request: Request, catalog: Cat, habitat: Habitat, family: Annotated[str, Query(max_length=30)] = "droplet_end_state",
                  fuel: Annotated[str | None, Query(max_length=30)] = None,
                  diluent: Annotated[Literal["nitrogen only", "helium", "carbon dioxide"] | None, Query()] = None,
                  habitat_view: Annotated[Literal["on", "off"], Query()] = "on") -> dict:
    """Flame Sweeper: the oxygen x pressure field for one experiment family, with the skill check and what to test next."""
    if family not in sweeper_mod.FAMILIES:
        raise HTTPException(404, f"unknown family {family!r}")
    if habitat_view == "off":                       # the Habitat view is off: nothing in the result may depend on a habitat
        habitat = None
    key = (id(catalog), family, fuel, diluent) + ((tuple(habitat["o2"]), tuple(habitat["pressure_psi"])) if habitat else ())
    if key not in _sweeper_cache:
        if len(_sweeper_cache) > 64:
            _sweeper_cache.clear()
        _sweeper_cache[key] = sweeper_mod.sweep(catalog, family, habitat, fuel, diluent)
    families = []
    for k, f in sweeper_mod.FAMILIES.items():
        rows, dropped = sweeper_mod.collect(catalog, k)
        families.append({"key": k, "label": f["label"], "short": f["short"], "tests": len(rows), "investigations": sorted({r["psi"] for r in rows})})
    return {"families": families, **_sweeper_cache[key]}


@router.get("/sources")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def sources(request: Request, catalog: Cat) -> dict:
    return {"sources": catalog.sources,
            "investigations": [{"id": i["id"], "name": i["name"], "title": i["title"], "doi": i["doi"],
                                "license": i["license"], "landing_url": i["landing_url"],
                                "record_source": i["record_source"]} for i in catalog.ordered()]}


@router.get("/experiment-vs-simulation")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def experiment_vs_simulation(request: Request, catalog: Cat, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """PSI-117's figure data, with experiment and simulation labelled apart. Never part of a count, model or pattern."""
    return extinction.charts(catalog, settings.snapshot_dir)


@router.get("/figure-data/{psi_id}")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def figure_data(request: Request, catalog: Cat, settings: Annotated[Settings, Depends(get_settings)],
                      psi_id: Annotated[str, Field(pattern=PSI_ID)]) -> dict:
    """Figure data stored from PSI's Analyzed Data files, drawn as published. Never part of a count, model or pattern."""
    return extinction.investigation_figures(catalog, settings.snapshot_dir, psi_id)


@router.get("/data-complexity")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def data_complexity(request: Request, catalog: Cat, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    """Why only part of PSI can be charted: what the tier-B tables hold, and how much data sits behind each investigation."""
    registry = ledger.load_registry(settings.data_dir / "variables.yaml")
    return {"tier_b": complexity.table_holdings(catalog, settings.snapshot_dir, registry), "layers": complexity.data_layers(catalog),
            "limits": {"analyzed_mb": complexity.ANALYZED_FEASIBLE_MB, "raw_mb": complexity.RAW_FEASIBLE_MB}}


@router.get("/quality")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def quality(request: Request, catalog: Cat) -> dict:
    """What the snapshot holds and what it doesn't, per investigation."""
    return {"fetched_at": catalog.manifest["fetched_at"],
            "investigations": [{"id": i["id"], "name": i["name"], "record_source": i["record_source"],
                                "record_fetched_at": i["record_fetched_at"], "doi": i["doi"], "license": i["license"],
                                "tables_status": i["tables_status"], "tables": i["tables"],
                                "method": i["method"]} for i in catalog.ordered()]}


@router.get("/si/status")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def si_status(request: Request, settings: Annotated[Settings, Depends(get_settings)],
                    http=Depends(get_http)) -> dict:
    installed = await ollama.installed_models(http, settings.ollama_url)
    model = settings.si_model
    if installed is None:
        return {"available": False, "model": model, "message": "Ollama isn't running. The dashboard's data views "
                "work without it; the SI assistant doesn't."}
    ok = ollama.is_installed(model, installed)
    return {"available": ok, "model": model,
            "message": None if ok else f"Model {model} isn't installed. Run: ollama pull {model}"}
