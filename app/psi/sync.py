"""Fetch the PSI combustion investigations into the committed snapshot in data/snapshot/.

    python -m app.psi.sync

What it downloads:
- every investigation the PSI search page lists for "combustion" (search hit + full record):
  all its text fields, publications, image names and the list of its files by folder;
- each record's *Experimental table* files (the per-test tables), up to a size cap;
- its documents: the Reports and Science Documents folders and any ReadMe file,
  as PDF, Word, Excel, text or CSV up to 5 MB each (see app/psi/documents.py).
  The files are kept in .cache/psi-docs/; their extracted text goes in the snapshot.

What it never downloads: Raw Data, video, images, or larger documents. CFI-G alone
holds about 2 TB in 3,749 raw files.

Contact details (emails, phone numbers, addresses) are removed before anything
is written. Nothing is silently cleaned: record text is kept exactly as PSI
publishes it, and every file's sha256 is recorded in the manifest.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.config import get_settings
from app.psi import analyzed, documents, workbooks
from app.psi.client import COLLECTION_URL, LANDING_URL, PSIClient, PSIError

log = logging.getLogger("spacesweepers.sync")

MAX_TABLE_BYTES = 5_000_000
TABLE_SUFFIXES = (".csv",)  # .xlsx tables are listed in the manifest as "not parsed"

# Record fields kept in the snapshot (PSI field name → snapshot name).
RECORD_FIELDS = {
    "accession": "id", "title": "title", "projectType": "project_type",
    "objective": "objective", "approach": "approach", "hypothesis": "hypothesis",
    "researchImpacts": "research_impacts", "experimentHardware": "experiment_hardware",
    "subResearchArea": "sub_research_area", "investigationAcronym": "acronym_record",
    "investigationStartDate": "start_date", "investigationEndDate": "end_date",
    "doi": "doi", "licenseIdentifier": "license_id", "licenseName": "license_name",
    "licenseLink": "license_link", "related_glds": "related_record",
    "version": "version", "versionReason": "version_reason",
    "modifiedDate": "modified_date", "releaseDate": "release_date",
    "managingNasaCenter": "nasa_center", "totalFileSize": "total_file_size",
    "proposalTitle": "proposal_title", "flightProgram": "flight_program", "spaceProgram": "sponsor",
    "experimentHardwareLink": "hardware_links", "description": "description",
    "acknowledgments": "acknowledgments", "missionName": "mission_name", "funding": "funding",
    "submissionDate": "submission_date",
}
# Search-hit fields that the full record lacks or spells differently.
HIT_FIELDS = {
    "Acronym": "acronym", "Flight Platform": "flight_platform", "Keywords": "keywords",
    "Related Investigations": "related_search", "Research Area": "research_area",
}
PII_KEYS = re.compile(r"email|phone|fax|address", re.I)

# The PSI search page matches the query word against these record fields. An
# investigation is kept when its research area is Combustion Science or when
# one of these fields mentions combustion. That reproduces the page's 26 hits:
# the 24 Combustion Science investigations plus PSI-108 (Fluid Physics) and
# PSI-181 (Materials Science), which mention combustion in their Earth benefits.
QUERY = "combustion"
SEARCH_FIELDS = ["Title", "Objectives", "Approach", "Hypothesis", "Keywords",
                 "Research Impacts/Earth Benefits", "Experiment Hardware", "Publication Title",
                 "Acronym", "SubResearch Area"]


def match_reason(hit: dict) -> str | None:
    """Why the search page lists this hit for the query, or None if it wouldn't."""
    if hit.get("Research Area") == "Combustion Science":
        return "Combustion Science research area"
    fields = [f for f in SEARCH_FIELDS if re.search(QUERY, str(hit.get(f) or ""), re.I)]
    return f"mentions {QUERY} in {', '.join(fields)}" if fields else None


def strip_pii(obj):
    """Drop contact details anywhere in a structure."""
    if isinstance(obj, dict):
        return {k: strip_pii(v) for k, v in obj.items() if not PII_KEYS.search(k)}
    if isinstance(obj, list):
        return [strip_pii(v) for v in obj]
    return obj


# When the full record can't be fetched, these search-hit fields stand in for it.
HIT_FALLBACK = {
    "Accession": "id", "Title": "title", "Project Type": "project_type", "Objectives": "objective",
    "Approach": "approach", "Hypothesis": "hypothesis", "Research Impacts/Earth Benefits": "research_impacts",
    "Experiment Hardware": "experiment_hardware", "SubResearch Area": "sub_research_area",
    "Investigation Start Date": "start_date", "Investigation End Date": "end_date",
    "Monitoring Center": "nasa_center",
}


def _status(publication: dict) -> str | None:
    status = publication.get("status")
    return status.get("annotationValue") if isinstance(status, dict) else None


def file_inventory(record: dict) -> dict[str, dict]:
    """PSI's files by folder: count, total size, and the names (except Raw Data, which has thousands)."""
    out: dict[str, dict] = {}
    for f in (record.get("added") or []) + (record.get("modified") or []):
        folder = _folder(f.get("remote_path", ""))
        entry = out.setdefault(folder, {"files": 0, "bytes": 0, "names": []})
        entry["files"] += 1
        entry["bytes"] += f.get("file_size") or 0
        if folder != "Raw Data":
            entry["names"].append(f.get("file_name"))
    for entry in out.values():
        entry["names"].sort()
    return out


def prune(hit: dict, record: dict | None) -> dict:
    """The snapshot form of one investigation: every useful field, no contacts, files listed not copied."""
    if record is None:  # no full record: fill what the search listing has
        record = {old: hit.get(h) for h, new in HIT_FALLBACK.items()
                  for old, n in RECORD_FIELDS.items() if n == new}
    out = {new: record.get(old) for old, new in RECORD_FIELDS.items()}
    out.update({new: hit.get(old) for old, new in HIT_FIELDS.items()})
    out["landing_url"] = LANDING_URL.format(psi_id=out["id"])
    out["publications"] = [{"title": p.get("title"), "doi": p.get("doi") or None,
                            "authors": p.get("authorList"), "status": _status(p)}
                           for p in record.get("publications") or []]
    out["images"] = [i.get("file_name") for i in record.get("images") or []]
    files = (record.get("added") or []) + (record.get("modified") or [])
    out["file_folders"] = dict(Counter(_folder(f.get("remote_path", "")) for f in files))
    out["file_inventory"] = file_inventory(record)
    # PSI's website has a "Modeling Table" section; its API had no such field on 2026-11-14.
    # Keep any table-like field that names modelling, so it shows up if PSI adds one.
    out["modeling_tables"] = [{"file": t.get("file_name"), "bytes": t.get("file_size")}
                              for key, value in record.items() if re.search(r"model", key, re.I) and isinstance(value, list)
                              for t in value if isinstance(t, dict)]
    out["experimental_tables"] = [{"file": t.get("file_name"), "bytes": t.get("file_size"),
                                   "s3_version_id": t.get("s3_version_id")}
                                  for t in record.get("experimentalTable") or []]
    return strip_pii(out)


def _folder(remote_path: str) -> str:
    parts = remote_path.split("/")
    return parts[4] if len(parts) > 5 else "(top level)"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


BREAKER = 2  # after this many record failures in a row, stop asking PSI for full records


def _load_raw(raw_dir: Path, psi_id: str) -> tuple[dict | None, str | None]:
    """A full record saved by an earlier sync, with the time it was fetched."""
    path = raw_dir / f"{psi_id}.json"
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if record.get("accession") != psi_id:
        return None, None
    fetched = datetime.fromtimestamp(path.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return record, fetched


async def _documents(client: PSIClient, psi_id: str, record: dict, out_dir: Path, docs_dir: Path,
                     downloads_failed: int) -> tuple[list[dict], int]:
    """Download (or reuse) and extract each document. Returns manifest entries and the failure count."""
    take, skip = documents.selection(record, workbooks.not_read())
    entries = [{**s, "status": f"not read: {s['reason']}", "text_file": None} for s in skip]
    for doc in take:
        name = doc["file"]
        cached = docs_dir / psi_id / Path(name).name
        data, reason = None, None
        if cached.exists() and cached.stat().st_size == doc["bytes"]:
            data = cached.read_bytes()
        elif downloads_failed < BREAKER:
            try:
                data = await client.download(psi_id, name, documents.MAX_DOC_BYTES)
                cached.parent.mkdir(parents=True, exist_ok=True)
                cached.write_bytes(data)
                downloads_failed = 0
            except (PSIError, httpx.HTTPError) as e:
                if not getattr(e, "file_missing", False):   # a missing file isn't an outage
                    downloads_failed += 1
                reason = str(e) or type(e).__name__
        else:
            reason = "PSI's download service was failing; not requested"
        if data is None:
            entries.append({**doc, "status": f"not read: download failed ({reason})", "text_file": None})
            continue
        result = documents.extract(name, data)
        text_file = None
        if result.text.strip():
            text_file = f"docs/{psi_id}/{Path(name).name}.txt"
            target = out_dir / text_file
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.text + "\n", encoding="utf-8")
        entries.append({**doc, "sha256": _sha256(data), "pages": result.pages, "characters": len(result.text),
                        "status": result.status, "text_file": text_file})
    return entries, downloads_failed


async def sync(out_dir: Path, http: httpx.AsyncClient, base: str, raw_dir: Path,
               docs_dir: Path | None = None) -> dict:
    """Write the snapshot. PSI's record and download services fail at times, so:

    - every full record PSI returns is also kept in raw_dir (outside the snapshot,
      because it holds contact details) and reused when PSI can't serve it;
    - a table already in the snapshot is kept when it can't be downloaded again;
    - an investigation with no full record is still listed, from the search hit,
      and marked `record_source: search listing` (no DOI, license or tables).
    """
    client = PSIClient(http, base)
    docs_dir = docs_dir or raw_dir.parent / "psi-docs"
    all_hits = await client.search(QUERY)
    hits = [h for h in all_hits if match_reason(h)]
    log.info("PSI search for %r: %d hits, %d match the search page's rule", QUERY, len(all_hits), len(hits))
    records_dir, tables_dir = out_dir / "records", out_dir / "tables"
    for d in (records_dir, tables_dir, raw_dir):
        d.mkdir(parents=True, exist_ok=True)

    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    manifest = {"fetched_at": now, "source": COLLECTION_URL, "api": base + "/geode-py/ws/repo",
                "query": QUERY, "api_hits": len(all_hits),
                "max_table_bytes": MAX_TABLE_BYTES, "max_document_bytes": documents.MAX_DOC_BYTES,
                "investigations": {}}
    failures = downloads_failed = 0
    for hit in sorted(hits, key=lambda h: int(h["Accession"].split("-")[1])):
        psi_id = hit["Accession"]
        record, record_error, source, record_fetched = None, None, "live", now
        if failures < BREAKER:
            try:
                record = await client.record(psi_id)
                (raw_dir / f"{psi_id}.json").write_text(json.dumps(record), encoding="utf-8")
                failures = 0
            except (PSIError, httpx.HTTPError) as e:
                failures += 1
                record_error = str(e) or type(e).__name__
        else:
            record_error = "PSI's record service was failing; not requested"
        if record is None:
            record, record_fetched = _load_raw(raw_dir, psi_id)
            source = "local cache" if record else "search listing"
            log.warning("%s: full record unavailable (%s); using the %s", psi_id, record_error, source)
        snap = prune(hit, record)
        snap["match_reason"] = match_reason(hit)
        snap["record_source"], snap["record_fetched_at"] = source, record_fetched or now
        entry = {"version": snap["version"], "research_area": snap["research_area"],
                 "match_reason": snap["match_reason"], "modified_date": snap["modified_date"], "doi": snap["doi"],
                 "license": snap["license_id"] or None, "record_source": source,
                 "record_fetched_at": snap["record_fetched_at"], "record_error": record_error,
                 "tables": [], "not_downloaded": []}
        for table in snap["experimental_tables"]:
            name = table["file"] or ""
            target = tables_dir / psi_id / Path(name).name
            if not name.lower().endswith(TABLE_SUFFIXES):
                entry["not_downloaded"].append({"file": name, "reason": "not a CSV file"})
                continue
            if (table["bytes"] or 0) > MAX_TABLE_BYTES:
                entry["not_downloaded"].append({"file": name, "reason": f"over {MAX_TABLE_BYTES} bytes"})
                continue
            data, kept = None, False
            if downloads_failed < BREAKER:
                try:
                    data = await client.download(psi_id, name, MAX_TABLE_BYTES)
                    downloads_failed = 0
                except (PSIError, httpx.HTTPError) as e:
                    if not getattr(e, "file_missing", False):   # a missing file isn't an outage
                        downloads_failed += 1
                    reason = str(e) or type(e).__name__
            else:
                reason = "PSI's download service was failing; not requested"
            if data is None and target.exists():
                data, kept = target.read_bytes(), True
            if data is None:
                entry["not_downloaded"].append({"file": name, "reason": reason})
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            entry["tables"].append({"file": f"tables/{psi_id}/{target.name}", "bytes": len(data),
                                    "sha256": _sha256(data), "s3_version_id": table["s3_version_id"],
                                    "kept_from_earlier_sync": kept})
        if record is not None:
            entries, downloads_failed = await _documents(client, psi_id, record, out_dir, docs_dir, downloads_failed)
            entry["documents"], entry["workbooks"] = documents.split_handled(entries)
            for line in workbooks.apply(psi_id, entry, docs_dir, out_dir):       # workbooks become one table each, once
                log.info("%s: %s", psi_id, line)
            for line in await analyzed.fetch(client, psi_id, snap, entry, out_dir):      # the few Analyzed Data files we store
                log.warning("%s: %s", psi_id, line)
        else:
            entry["documents"] = []
        text = json.dumps(snap, indent=1, ensure_ascii=False)
        (records_dir / f"{psi_id}.json").write_text(text + "\n", encoding="utf-8")
        entry["record_sha256"] = _sha256(text.encode())
        manifest["investigations"][psi_id] = entry
        log.info("%s: record from %s, %d table(s), %d not downloaded", psi_id, source, len(entry["tables"]),
                 len(entry["not_downloaded"]))
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    return manifest


async def _main(out_dir: Path) -> None:
    settings = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.upstream_timeout_seconds, connect=10),
                                 follow_redirects=False, headers={"User-Agent": "SpaceSweepers/0.2 (PSI sync)"}) as http:
        manifest = await sync(out_dir, http, settings.psi_base, settings.cache_dir / "psi-raw")
    inv = manifest["investigations"].values()
    sources = Counter(e["record_source"] for e in inv)
    docs = Counter(d["status"].split(":")[0] for e in inv for d in e.get("documents", []))
    print(f"{len(manifest['investigations'])} investigations ({dict(sources)}), "
          f"{sum(len(e['tables']) for e in inv)} tables, documents {dict(docs)}, saved to {out_dir}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=get_settings().snapshot_dir)
    asyncio.run(_main(parser.parse_args().out))
