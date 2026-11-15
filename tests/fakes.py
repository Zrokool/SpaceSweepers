"""Offline stand-ins for NASA PSI and Ollama, shaped like the live services (2026-11-14)."""

from __future__ import annotations

import json

import httpx

TABLE_NAME = "PSI-900_Experimental table_Demo.csv"
# The messy cases seen in real PSI tables: blank rows, a note row, "~", ranges, lists, "none", negatives.
TABLE_CSV = (
    "Test,Fuel,XO2,P (atm),CO (ppm),Ignited\n"
    "T1,PMMA,0.21,1,12,Yes\n"
    "T2,PMMA,~0.30,0.69,none,yes\n"
    "T3,cotton,21.5 - 21.7,1 ,-1,No\n"
    "T4,cotton,0.17; 0.21; 0.25,1,5,flash\n"
    ",,,,,\n"
    ",note: fan failed on day 3,,,,\n"
    "T5,PMMA,0.34,0.5,abc,No\n"
).encode()


def hit(psi_id: str, **over) -> dict:
    base = {"Accession": psi_id, "Title": f"Demo investigation {psi_id}", "Research Area": "Combustion Science",
            "Project Type": "Microgravity Investigation", "Flight Platform": "International Space Station (ISS)",
            "Objectives": "Study flame spread over solid fuel samples.", "Approach": "Tests were conducted aboard the ISS.",
            "Hypothesis": "", "Keywords": "Flame Spread     Fire Safety", "Acronym": "DEMO", "SubResearch Area": "Fire Safety",
            "Related Investigations": "", "Research Impacts/Earth Benefits": "Better fire safety.",
            "Experiment Hardware": {"Name": "Microgravity Science Glovebox (MSG)", "Link": "https://example.invalid/msg"}}
    return {**base, **over}


def record(psi_id: str, tables: list[str] = (), **over) -> dict:
    base = {"accession": psi_id, "title": f"Demo investigation {psi_id}", "projectType": "Microgravity Investigation",
            "objective": "Study flame spread over solid fuel samples.", "approach": "Tests were conducted aboard the ISS.",
            "doi": "10.60555/demo-0001", "licenseIdentifier": "CC0-1.0", "version": 2, "related_glds": "",
            "experimentHardware": "Microgravity Science Glovebox (MSG)",
            "contacts": [{"firstName": "Ada", "lastName": "Lovelace", "email": "ada@example.edu", "phone": "555-0100",
                          "address": "1 Lab Way"}],
            "publications": [{"title": "A paper", "doi": "10.1000/x", "authorList": "Lovelace A."}],
            "added": [{"remote_path": f"/Home/psi-data/{psi_id}/Raw Data/huge.mp4", "file_name": "huge.mp4", "file_size": 9e9}],
            "modified": [],
            "experimentalTable": [{"file_name": t, "file_size": len(TABLE_CSV), "s3_version_id": "v1"} for t in tables]}
    return {**base, **over}


def make_psi(hits: list[dict], records: dict[str, dict], *, record_status: int = 200, download_status: int = 200,
             download_host: str = "psi-repo-prod.s3.amazonaws.com"):
    """An httpx handler imitating PSI's search, record and download endpoints."""
    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.host == "psi.nasa.gov" and url.path == "/geode-py/ws/repo/search":
            return httpx.Response(200, json={"hits": {"total": len(hits), "hits": [{"_source": h} for h in hits]}})
        if url.host == "psi.nasa.gov" and url.path.startswith("/geode-py/ws/repo/investigations/"):
            psi_id = url.path.rsplit("/", 1)[1]
            if record_status != 200 or psi_id not in records:
                return httpx.Response(500, json={"message": "Internal Server Error"})
            return httpx.Response(200, json=records[psi_id])
        if url.host == "psi.nasa.gov" and url.path.endswith("/download"):
            if download_status != 200:
                return httpx.Response(download_status)
            return httpx.Response(200, text=f"https://{download_host}/psi-data/file.csv?sig=abc")
        if url.host == download_host:
            return httpx.Response(200, content=TABLE_CSV, headers={"content-length": str(len(TABLE_CSV))})
        return httpx.Response(404)
    return handler


def make_ollama(answers: list[dict], models=("granite3.3:2b",)):
    """An httpx handler imitating Ollama: returns the queued answers in order, recording each request."""
    queue, seen = list(answers), []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in models]})
        if request.url.path == "/api/chat":
            seen.append(json.loads(request.content))
            answer = queue.pop(0) if queue else {}
            content = answer if isinstance(answer, str) else json.dumps(answer)
            return httpx.Response(200, json={"message": {"content": content}})
        return httpx.Response(404)
    handler.seen = seen
    return handler


def make_ollama_fn(respond, models=("granite3.3:2b",)):
    """Like make_ollama, but `respond(role, system, user, body)` decides each answer, so a test can read the real prompt.

    role is "investigator" or "analyst", from the system prompt. Returns a dict (sent as JSON) or a string (sent as is).
    """
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in models]})
        if request.url.path == "/api/chat":
            body = json.loads(request.content)
            system, user = body["messages"][0]["content"], body["messages"][-1]["content"]
            role = "investigator" if system.startswith("You are the Investigator") else "analyst"
            seen.append({"role": role, "body": body})
            answer = respond(role, system, user, body)
            return httpx.Response(200, json={"message": {"content": answer if isinstance(answer, str) else json.dumps(answer)}})
        return httpx.Response(404)
    handler.seen = seen
    return handler
