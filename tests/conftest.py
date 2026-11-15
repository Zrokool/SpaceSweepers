"""Test fixtures: the app with its outbound HTTP replaced by a mock transport.

Tests run offline against the committed PSI snapshot in data/; only the network
(PSI, Ollama) is faked.
"""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.deps import limiter
from app.main import app

Handler = Callable[[httpx.Request], httpx.Response]


def _offline(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("tests are offline", request=request)


@pytest.fixture
def make_client(tmp_path):
    limiter.enabled = False
    # Built-in defaults (never the developer's .env); caches and run logs go to a temp dir.
    app.dependency_overrides[get_settings] = lambda: Settings(_env_file=None, cache_dir=tmp_path)

    def factory(handler: Handler = _offline) -> TestClient:
        # TestClient without a `with` block skips the lifespan, so no real client is opened.
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return TestClient(app, base_url="http://localhost")

    yield factory
    limiter.enabled = True
    app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def client(make_client):
    return make_client()


@pytest.fixture(scope="session")
def catalog_and_library():
    from app.catalog import load_catalog
    from app.insights.library import build_library
    data = Path(__file__).resolve().parent.parent / "data"
    catalog = load_catalog(data)
    return catalog, build_library(catalog, data)
