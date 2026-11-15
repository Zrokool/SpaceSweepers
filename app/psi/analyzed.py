"""PSI "Analyzed Data" files: the data behind figures in the investigators' papers.

Only the files listed in data/analyzed.yaml are stored, each unchanged, with its SHA-256, DOI and licence in the manifest.
Rule: one stored copy of every fact. Raw Data (terabytes) is never downloaded.

    python -m app.psi.analyzed        # download the listed files into the snapshot and record them in the manifest
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from functools import lru_cache
from pathlib import Path

import httpx
import yaml

from app.config import ROOT, get_settings
from app.psi.client import PSIClient, PSIError

log = logging.getLogger("spacesweepers.analyzed")
RECIPES = ROOT / "data" / "analyzed.yaml"


@lru_cache
def load(path: Path = RECIPES) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def wanted(psi_id: str, path: Path = RECIPES) -> list[dict]:
    return list((load(path).get("files") or {}).get(psi_id) or [])


async def fetch(client: PSIClient, psi_id: str, record: dict | None, entry: dict, out_dir: Path, path: Path = RECIPES) -> list[str]:
    """Download this investigation's listed files into out_dir/analyzed/<psi_id>/ and record them in its manifest entry."""
    files, lines = wanted(psi_id, path), []
    if not files:
        return lines
    limit, target_dir = load(path).get("max_bytes", 5_000_000), out_dir / "analyzed" / psi_id
    target_dir.mkdir(parents=True, exist_ok=True)
    listed = {n for f in ((record or {}).get("file_inventory") or {}).get("Analyzed Data", {}).get("names", [])} if record else set()
    entry["analyzed"] = []
    for f in files:
        target = target_dir / f["file"]
        data, kept = None, False
        try:
            data = await client.download(psi_id, f["file"], limit)
        except (PSIError, httpx.HTTPError) as e:
            lines.append(f"{f['file']}: {e}")
        if data is None and target.exists():
            data, kept = target.read_bytes(), True
        if data is None:
            continue
        target.write_bytes(data)
        entry["analyzed"].append({"file": f"analyzed/{psi_id}/{f['file']}", "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                                  "figure": f.get("figure"), "charted": bool(f.get("charted")), "kept_from_earlier_sync": kept,
                                  "doi": entry.get("doi"), "license": entry.get("license")})
    return lines


async def _main(snapshot: Path) -> None:
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    settings = get_settings()
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.upstream_timeout_seconds, connect=10), follow_redirects=False,
                                 headers={"User-Agent": "SpaceSweepers/0.2 (PSI analyzed data)"}) as http:
        client = PSIClient(http, settings.psi_base)
        for psi_id in load().get("files", {}):
            entry = manifest["investigations"][psi_id]
            for line in await fetch(client, psi_id, None, entry, snapshot):
                log.warning("%s: %s", psi_id, line)
            log.info("%s: %d analyzed file(s) stored", psi_id, len(entry.get("analyzed", [])))
    (snapshot / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)      # presigned download links carry short-lived tokens: never log them
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot", type=Path, default=get_settings().snapshot_dir)
    asyncio.run(_main(parser.parse_args().snapshot))
