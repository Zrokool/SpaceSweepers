"""PSI client and sync: URL safety, the 26-investigation scope, contact removal, and PSI outages."""

import asyncio
import json

import httpx
import pytest

from app.psi import sync as sync_mod
from app.psi.client import PSIClient, PSIError, check_download_url, check_id
from tests.fakes import TABLE_NAME, hit, make_psi, record


def run_sync(tmp_path, handler):
    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await sync_mod.sync(tmp_path / "snapshot", http, "https://psi.nasa.gov", tmp_path / "raw")
    return asyncio.run(go())


def test_ids_and_download_hosts_are_validated():
    assert check_id("PSI-159") == "PSI-159"
    for bad in ["PSI-159/../x", "psi-1", "PSI-", "PSI-1?x=1", ""]:
        with pytest.raises(PSIError):
            check_id(bad)
    check_download_url("https://psi-repo-prod.s3.amazonaws.com/psi-data/a.csv?sig=1")
    check_download_url("https://psi-curation-prod.s3.amazonaws.com/psi-data/a.pdf?sig=1")
    for bad in ["http://psi-repo-prod.s3.amazonaws.com/a", "https://evil.example/a", "file:///etc/passwd",
                "https://psi-repo-prod.s3.amazonaws.com.evil.example/a", "https://psi-repo-prod.s3.amazonaws.com:8443/a",
                "https://psi-other-prod.s3.amazonaws.com/a", "https://evil-psi-curation-prod.s3.amazonaws.com/a"]:
        with pytest.raises(PSIError):
            check_download_url(bad)


def test_download_refuses_a_link_to_another_host():
    handler = make_psi([], {}, download_host="evil.example")

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await PSIClient(http).download("PSI-900", TABLE_NAME, 1000)
    with pytest.raises(PSIError, match="unexpected download host"):
        asyncio.run(go())


def test_scope_matches_the_psi_search_page():
    """The API returns every investigation; the page keeps combustion science plus text mentions."""
    assert sync_mod.match_reason(hit("PSI-1")) == "Combustion Science research area"
    fluid = hit("PSI-2", **{"Research Area": "Fluid Physics", "Objectives": "Thermocapillary flow.", "Approach": "",
                             "Keywords": "", "Research Impacts/Earth Benefits": "Used in the study of combustion."})
    assert sync_mod.match_reason(fluid) == "mentions combustion in Research Impacts/Earth Benefits"
    other = hit("PSI-3", **{"Research Area": "Biophysics", "Objectives": "Protein crystals.", "Approach": "", "Keywords": "",
                             "Research Impacts/Earth Benefits": "Medicine.", "Title": "Crystals"})
    assert sync_mod.match_reason(other) is None


def test_sync_saves_records_and_tables_without_contact_details(tmp_path):
    manifest = run_sync(tmp_path, make_psi([hit("PSI-900")], {"PSI-900": record("PSI-900", [TABLE_NAME])}))
    entry = manifest["investigations"]["PSI-900"]
    assert entry["record_source"] == "live" and entry["doi"] == "10.60555/demo-0001" and entry["license"] == "CC0-1.0"
    assert [t["file"] for t in entry["tables"]] == [f"tables/PSI-900/{TABLE_NAME}"]
    snapshot_text = "".join(p.read_text() for p in (tmp_path / "snapshot").rglob("*.json"))
    for secret in ["ada@example.edu", "555-0100", "1 Lab Way", "Lovelace\", \"email"]:
        assert secret not in snapshot_text
    saved = json.loads((tmp_path / "snapshot" / "records" / "PSI-900.json").read_text())
    assert saved["file_folders"] == {"Raw Data": 1}  # counted, never downloaded
    assert "contacts" not in saved


def test_sync_survives_a_psi_outage_and_never_downgrades(tmp_path):
    hits = [hit("PSI-900"), hit("PSI-901"), hit("PSI-902")]
    records = {"PSI-900": record("PSI-900", [TABLE_NAME])}
    run_sync(tmp_path, make_psi(hits, records))                      # first sync: PSI-900 is fully available
    manifest = run_sync(tmp_path, make_psi(hits, {}, record_status=500, download_status=500))   # then PSI fails
    inv = manifest["investigations"]
    assert inv["PSI-900"]["record_source"] == "local cache" and inv["PSI-900"]["doi"] == "10.60555/demo-0001"
    assert inv["PSI-900"]["tables"][0]["kept_from_earlier_sync"] is True
    assert inv["PSI-901"]["record_source"] == "search listing" and inv["PSI-901"]["doi"] is None
    # After two failures in a row the sync stops asking, instead of waiting on every record.
    assert "not requested" in inv["PSI-902"]["record_error"]
    saved = json.loads((tmp_path / "snapshot" / "records" / "PSI-901.json").read_text())
    assert saved["approach"] == "Tests were conducted aboard the ISS." and saved["experimental_tables"] == []
