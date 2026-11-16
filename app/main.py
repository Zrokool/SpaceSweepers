"""SpaceSweepers: an SI-powered dashboard of NASA PSI combustion research for space fire safety."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import ROOT, get_settings
from app.deps import limiter
from app.routes import dashboard, insights
from app.si import ollama
from app.warm import warm

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("spacesweepers")

STATIC = ROOT / "static"

CSP = "; ".join([
    "default-src 'self'",
    # Only this origin's scripts: no inline scripts, no eval, no third-party JS.
    "script-src 'self'",
    "style-src 'self' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data:",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])
# Swagger UI at /docs loads its assets from jsDelivr.
DOCS_CSP = ("default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "img-src 'self' data: https://fastapi.tiangolo.com; frame-ancestors 'none'")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.http = httpx.AsyncClient(
        timeout=settings.upstream_timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "SpaceSweepers/0.2 (+FastAPI)"},
        limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
    )
    try:
        await asyncio.to_thread(warm)        # build the catalog and search library now, not on the first visitor's request
    except RuntimeError:
        log.exception("packaged data failed its start-up check")
    try:                                                      # say at start-up if the SI model is missing; the dashboard runs either way
        level, message = await ollama.startup_report(app.state.http, settings.ollama_url, settings.si_model)
        getattr(log, level)(message)
    except Exception:
        log.exception("could not check the SI model at start-up")
    try:
        yield
    finally:
        await app.state.http.aclose()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="SpaceSweepers", version="0.2.0", lifespan=lifespan)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    if settings.allowed_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins,
                           allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        docs = request.url.path in ("/docs", "/redoc")
        response.headers["Content-Security-Policy"] = DOCS_CSP if docs else CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-cache"      # always revalidate (ETag): a browser never runs one page's new script against another's old one
        return response

    app.include_router(dashboard.router)
    app.include_router(insights.router)
    app.include_router(insights.sweeper_router)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    return app


app = create_app()
