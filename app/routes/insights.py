"""SI Insights API: ask a question (streamed), starter questions, what the library holds, and passage lookup."""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.analysis import sweeper as sweeper_mod
from app.analysis.habitats import HABITATS
from app.catalog import get_catalog
from app.config import Settings, get_settings
from app.deps import get_http, limiter
from app.analysis import queries
from app.insights import micro_flame, pipeline
from app.psi.units import convert
from app.insights.frame import reader_for
from app.insights.library import KIND_LABEL, Library, get_library
from app.insights.tools import Toolbox
from app.insights.verify import Checker
from app.si import ollama

router = APIRouter(prefix="/api/insights", tags=["insights"])
sweeper_router = APIRouter(prefix="/api/sweeper", tags=["sweeper"])      # Micro-Flame's explanation belongs to the Flame Sweeper view
PSI_ID = r"^PSI-\d{1,5}$"
ITEM_ID = re.compile(r"^[A-Z]:PSI-\d{1,5}(?::[A-Za-z0-9._-]{1,40}){0,3}$")


@lru_cache
def get_engine(data_dir: Path) -> tuple[Library, Toolbox, Checker]:
    library = get_library(data_dir)
    return library, Toolbox(library), Checker(library.catalog, reader_for(library.catalog))


def engine(settings: Annotated[Settings, Depends(get_settings)]) -> tuple[Library, Toolbox, Checker]:
    return get_engine(settings.data_dir)


Engine = Annotated[tuple[Library, Toolbox, Checker], Depends(engine)]


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    psi_ids: list[Annotated[str, Field(pattern=PSI_ID)]] = Field(default_factory=list, max_length=4)


class ScenarioInput(BaseModel):
    """The Scenario builder: what the user chose in the form. Every field is checked against fixed lists and numeric limits."""
    model_config = ConfigDict(extra="forbid")
    goal: Literal["nearest", "outcomes", "threshold", "compare", "profile"]
    target: Literal["burn", "extinguish", "ignite", "reignite"] | None = None
    fuel: str | None = Field(default=None, max_length=40)
    diluent: Literal["helium", "carbon dioxide", "nitrogen only"] | None = None
    o2_percent: float | None = Field(default=None, gt=0, le=100)
    pressure: float | None = Field(default=None, gt=0, le=1000)
    pressure_unit: Literal["psi", "atm", "kpa"] = "psi"
    variable: Literal["o2", "p"] | None = None

    def structured(self) -> dict:
        if self.fuel and self.fuel not in queries.FUEL_ALIASES:
            raise HTTPException(422, "unknown fuel or material")
        return {"goal": self.goal, "target": self.target, "fuel": self.fuel, "diluent": self.diluent, "variable": self.variable,
                "o2": None if self.o2_percent is None else self.o2_percent / 100,
                "p_psi": None if self.pressure is None else convert(self.pressure, self.pressure_unit, "pressure_psi")}


class ScenarioContext(BaseModel):
    """The conditions of the last answer, sent back so a follow-up can build on them (guided mode). Every field is checked."""
    model_config = ConfigDict(extra="forbid")
    goal: Literal["nearest", "outcomes", "threshold", "compare", "profile"]
    target: Literal["burn", "extinguish", "ignite", "reignite"] | None = None
    variable: Literal["o2", "p"] | None = None
    fuel: str | None = Field(default=None, max_length=40)
    diluent: Literal["helium", "carbon dioxide", "nitrogen only"] | None = None
    o2: float | None = Field(default=None, gt=0, le=1)
    p_psi: float | None = Field(default=None, gt=0, le=1000)

    def clean(self) -> dict:
        if self.fuel and self.fuel not in queries.FUEL_ALIASES:
            raise HTTPException(422, "unknown fuel or material")
        return self.model_dump()


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=2, max_length=500)
    history: list[Turn] = Field(default_factory=list, max_length=3)
    scenario: ScenarioInput | None = None
    audience: Literal["guided", "expert"] = "expert"          # guided = plain wording and follow-ups that build on the last answer; expert = unchanged
    context: ScenarioContext | None = None
    habitat: str | None = Field(default=None, max_length=12)       # the reference habitat chosen on the page; used only for counts from PSI tests


@router.post("/ask", response_class=StreamingResponse)
@limiter.limit(lambda: get_settings().ask_rate_limit)
async def ask(request: Request, body: AskRequest, eng: Engine, settings: Annotated[Settings, Depends(get_settings)],
              http=Depends(get_http)) -> StreamingResponse:
    """Streams server-sent events: frame, stage…, tools, report, done. Each event is one `data: {json}` line."""
    library, toolbox, checker = eng
    question = re.sub(r"\s+", " ", body.question).strip()
    if len(question) < 2:
        raise HTTPException(422, "ask a question")
    previous = body.history[-1].psi_ids if body.history else []
    if body.habitat is not None and body.habitat not in HABITATS:
        raise HTTPException(404, f"unknown habitat {body.habitat!r}")
    habitat = {"key": body.habitat, **HABITATS[body.habitat]} if body.habitat else None
    stream = pipeline.run(question=question, previous=previous, http=http, settings=settings, library=library,
                          toolbox=toolbox, checker=checker, habitat=habitat,
                          scenario=body.scenario.structured() if body.scenario else None, audience=body.audience,
                          context=body.context.clean() if body.context else None)
    return StreamingResponse(stream, media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.post("/warm")
@limiter.limit(lambda: get_settings().ask_rate_limit)
async def warm(request: Request, settings: Annotated[Settings, Depends(get_settings)], http=Depends(get_http)) -> dict:
    """Load the SI model into memory so the first question isn't slow. Safe to call any time."""
    installed = await ollama.installed_models(http, settings.ollama_url)
    if installed is None:
        return {"ready": False, "model": settings.si_model, "message": "Ollama isn't running."}
    if not ollama.is_installed(settings.si_model, installed):
        return {"ready": False, "model": settings.si_model, "message": f"Model {settings.si_model} isn't installed. Run: ollama pull {settings.si_model}"}
    try:
        seconds = await ollama.warm_up(http, settings.ollama_url, settings.si_model, settings.si_keep_alive, settings.si_timeout_seconds)
    except ollama.SIError as e:
        return {"ready": False, "model": settings.si_model, "message": str(e)}
    return {"ready": True, "model": settings.si_model, "seconds": seconds}


STARTERS = [
    ("Which investigations were simulations?", None),
    ("How many ground studies reuse flight data?", None),
    ("What did FLEX find about extinction?", "FLEX"),
    ("Which BASS-II tests recorded carbon monoxide?", "BASS-II"),
    ("What does SAME say about smoke particle size?", "SAME"),
    ("Compare BASS and BASS-II", "BASS-II"),
    ("Which documents does PSI hold for SAFFIRE-I?", "SAFFIRE-I"),
    ("What are the publications for SPICE about soot?", "SPICE"),
]


@router.get("/suggestions")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def suggestions(request: Request, eng: Engine) -> dict:
    library, _, _ = eng
    names = {i["name"] for i in library.catalog.ordered()}
    return {"starters": [q for q, needs in STARTERS if needs is None or needs in names]}


@router.get("/scenario-options")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def scenario_options(request: Request, eng: Engine) -> dict:
    """What the Scenario builder can offer: only fuels, gases and ranges that exist in the mapped tests, with their test counts."""
    library, _, _ = eng
    rows = queries.all_rows(library.catalog)
    fuels = Counter(r["fuel_key"] for r in rows if r["fuel_key"])
    diluents = Counter(r["diluent"] for r in rows)
    with_outcome = [r for r in rows if r["outcome"]]
    return {"fuels": [{"name": k, "tests": n} for k, n in fuels.most_common()], "diluents": [{"name": k, "tests": n} for k, n in diluents.most_common()],
            "tests": len(rows), "with_outcome": len(with_outcome),
            "o2_percent": [round(min(r["o2"] for r in rows) * 100, 1), round(max(r["o2"] for r in rows) * 100, 1)],
            "pressure_psi": [round(min(r["p_psi"] for r in rows), 1), round(max(r["p_psi"] for r in rows), 1)]}


@router.get("/library")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def library_info(request: Request, eng: Engine, settings: Annotated[Settings, Depends(get_settings)]) -> dict:
    library, _, _ = eng
    counts = library.counts()
    return {"items": len(library.items), "by_kind": [{"kind": k, "label": KIND_LABEL[k], "count": n} for k, n in sorted(counts.items())],
            "investigations": len(library.catalog.investigations), "model": settings.si_model,
            "documents_not_read": library.unread, "snapshot": library.catalog.manifest["fetched_at"]}


def _neighbours(library: Library, item) -> list[dict]:
    parts = item.id.split(":")
    out = []
    if item.kind in ("D", "R") and parts[-1].isdigit():
        for delta in (-1, 1):
            other = library.get(":".join(parts[:-1] + [str(int(parts[-1]) + delta)]))
            if other:
                out.append({"position": "before" if delta < 0 else "after", "id": other.id, "text": other.text})
    elif item.kind == "T" and item.row:
        for delta in (-1, 1):
            other = library.get(f"{':'.join(parts[:-1])}:row{item.row + delta}")
            if other:
                out.append({"position": "before" if delta < 0 else "after", "id": other.id, "text": other.text})
    return out


@router.get("/passage/{item_id}")
@limiter.limit(lambda: get_settings().api_rate_limit)
async def passage(request: Request, item_id: str, eng: Engine) -> dict:
    library, _, _ = eng
    if not ITEM_ID.match(item_id):
        raise HTTPException(422, "not an evidence id")
    item = library.get(item_id)
    if item is None:
        raise HTTPException(404, "no such passage")
    return {**library.source(item), "text": item.text, "neighbours": _neighbours(library, item)}


class ExplainRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    family: str = Field(max_length=30)
    fuel: str | None = Field(default=None, max_length=30)
    diluent: str | None = Field(default=None, pattern=r"^(nitrogen only|helium|carbon dioxide)$")
    habitat: str = Field(default="moon", max_length=12)


@sweeper_router.post("/explain")
@limiter.limit(lambda: get_settings().ask_rate_limit)
async def explain(request: Request, body: ExplainRequest, eng: Engine, settings: Annotated[Settings, Depends(get_settings)],
                  http=Depends(get_http)) -> dict:
    """Micro-Flame: a checked, at most three-sentence physical explanation of the Flame Sweeper patterns for one selection."""
    if body.family not in sweeper_mod.FAMILIES:
        raise HTTPException(404, f"unknown family {body.family!r}")
    if body.habitat not in HABITATS:
        raise HTTPException(404, f"unknown habitat {body.habitat!r}")
    library, _, checker = eng
    result = sweeper_mod.sweep(get_catalog(settings.data_dir), body.family, {"key": body.habitat, **HABITATS[body.habitat]}, body.fuel, body.diluent)
    return (await micro_flame.explain(http, settings, library, checker, result)).as_dict()
