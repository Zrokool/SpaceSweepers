"""At start-up the server says in its log whether Ollama is reachable and the SI model is installed."""

import asyncio
import logging

import httpx
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.si import ollama

MODEL = "granite3.3:2b"


def report(handler):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await ollama.startup_report(http, "http://ollama.test:11434", MODEL)
    return asyncio.run(go())


def tags(*names):
    return lambda request: httpx.Response(200, json={"models": [{"name": n} for n in names]})


def test_an_unreachable_ollama_is_a_warning_that_says_how_to_fix_it():
    def down(request):
        raise httpx.ConnectError("refused", request=request)
    level, message = report(down)
    assert level == "warning" and "not reachable at http://ollama.test:11434" in message
    assert f"ollama pull {MODEL}" in message and "SS_OLLAMA_URL" in message and "works without it" in message


def test_a_missing_model_is_a_warning_that_names_the_pull_command_and_what_is_installed():
    level, message = report(tags("granite3.3:8b", "llama3:latest"))
    assert level == "warning" and f"SI model {MODEL} is not installed" in message
    assert "granite3.3:8b, llama3:latest" in message and f"Run: ollama pull {MODEL}" in message
    assert "installed: none" in report(tags())[1]


def test_an_installed_model_is_reported_as_ready_including_the_latest_tag():
    assert report(tags(MODEL))[0] == "info" and report(tags(f"{MODEL}:latest"))[0] == "info"


def test_the_server_logs_the_check_at_start_up_and_still_starts_when_ollama_is_missing(monkeypatch, caplog):
    async def missing(http, url):
        return ["granite3.3:8b"]
    monkeypatch.setattr(ollama, "installed_models", missing)
    get_settings.cache_clear()
    with caplog.at_level(logging.INFO, logger="spacesweepers"), TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/meta").status_code == 200                       # the dashboard is up
    assert any("is not installed in Ollama" in r.getMessage() and r.levelno == logging.WARNING for r in caplog.records)


def test_a_failure_of_the_check_itself_never_stops_the_server(monkeypatch, caplog):
    async def boom(http, url, model):
        raise RuntimeError("unexpected")
    monkeypatch.setattr(ollama, "startup_report", boom)
    with caplog.at_level(logging.INFO, logger="spacesweepers"), TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/meta").status_code == 200
    assert any("could not check the SI model" in r.getMessage() for r in caplog.records)
