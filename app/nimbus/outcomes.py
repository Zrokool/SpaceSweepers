"""Document-derived outcomes: the ignition result of each BASS run, read from its observations note.

For each test the Outcome pointer (SI, Nimbus/agents/16-outcome-pointer.md) points at the sentence that says whether the
sample ignited and burned; fixed rules (O-1 to O-4) classify that sentence and check it. SI never writes an outcome.
Results are stored as references (table row and the table's SHA-256 -> class and quote), never as copies of conditions.

    python -m app.nimbus.outcomes                      # every BASS run, write data/outcome_evidence.json
    python -m app.nimbus.outcomes --out staging.json   # write elsewhere and leave the app's evidence alone
    python -m app.nimbus.outcomes --no-si              # list the candidates only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.catalog import load_catalog, read_table
from app.config import get_settings
from app.nimbus import spec
from app.nimbus.method import sentences
from app.si import ollama

log = logging.getLogger("spacesweepers.outcomes")

AGENT_FILE = "16-outcome-pointer.md"
TARGET = {"investigation": "PSI-26", "table": "PSI-26_Workbook table_BASS As Run.csv", "observations": "Test Observations", "test": "Test no.", "material": "material"}
CLASSES = ("burned", "no_ignition")

NO_IGNITION = re.compile(r"\b(no ignition|did not ignite|didn'?t ignite|failed to ignite|never ignited|would not ignite|not ignite[d]?|ignition failed|failed ignition)\b", re.I)
BURNED = re.compile(r"\b(ignited|burn(?:ed|ing|s)?|spread(?:ing|s)?)\b", re.I)
NEGATED_BURN = re.compile(r"\b(not|no|never|didn'?t|wouldn'?t)\W+(?:\w+\W+){0,2}(?:ignit\w*|burn\w*|spread\w*)\b", re.I)


def classify(sentence: str) -> str | None:
    """O-2: the class comes from this sentence alone."""
    if NO_IGNITION.search(sentence):
        return "no_ignition"
    if BURNED.search(sentence) and not NEGATED_BURN.search(sentence):
        return "burned"
    return None


def numbered(note: str) -> dict[str, str]:
    return {f"S{n}": s for n, s in enumerate(sentences(note), 1)}


def candidates(note: str) -> list[str]:
    """O-1: sentences with an ignition or burning cue, in order."""
    return [sid for sid, s in numbered(note).items() if NO_IGNITION.search(s) or BURNED.search(s)]


def decide(note: str, proposal: str | None) -> dict:
    """Turn SI's pointer into a stored entry. Code decides the class."""
    ids, cands = numbered(note), candidates(note)
    sid = str(proposal or "none").strip().rstrip(":")
    if sid == "none" or sid not in cands:
        return {"status": "none", "class": None, "id": None, "quote": None, "review": bool(cands) and sid == "none"}
    cls = classify(ids[sid])
    if cls is None:
        return {"status": "none", "class": None, "id": None, "quote": None, "review": False}
    opposite = "burned" if cls == "no_ignition" else "no_ignition"
    if any(classify(s) == opposite for k, s in ids.items() if k != sid):      # O-3: the note contradicts itself
        return {"status": "conflict", "class": None, "id": sid, "quote": ids[sid], "review": True}
    return {"status": "evidence", "class": cls, "id": sid, "quote": ids[sid], "review": False}


def user_message(row: dict, note: str, cands: list[str]) -> str:
    ids = numbered(note)
    return spec.agent(AGENT_FILE).user_template.format(
        test=row.get(TARGET["test"], "?"), material=row.get(TARGET["material"], "?"),
        sentences="\n".join(f"{k}: {v}" for k, v in ids.items()), candidates=", ".join(cands) or "none")


async def point(http: httpx.AsyncClient, url: str, model: str, row: dict, note: str, timeout: float) -> dict:
    cands = candidates(note)
    if not cands:
        return decide(note, "none")
    agent = spec.agent(AGENT_FILE)
    schema = json.loads(json.dumps(agent.output_schema))
    schema["properties"]["evidence"]["enum"] = [*cands, "none"]                # SI can only point at a candidate, or say none
    try:
        answer = await ollama.chat_json(http, url, model, agent.system_prompt, user_message(row, note, cands), schema, timeout, agent.meta.get("options"))
    except ollama.SIError as e:
        return {"status": "not assessed", "class": None, "id": None, "quote": None, "review": False, "reason": str(e)}
    return decide(note, answer.get("evidence"))


async def run(data_dir: Path, model: str, out_path: Path, use_si: bool = True) -> dict:
    settings = get_settings()
    catalog = load_catalog(data_dir)
    table = next(t for t in catalog.manifest["investigations"][TARGET["investigation"]]["tables"] if t["file"].endswith(TARGET["table"]))
    header, rows = read_table(data_dir / "snapshot", table)
    obs = next(i for i, h in enumerate(header) if h.startswith(TARGET["observations"]))
    results: dict[str, dict] = {}
    async with httpx.AsyncClient() as http:
        if use_si:
            installed = await ollama.installed_models(http, settings.ollama_url)
            if installed is None or not ollama.is_installed(model, installed):
                raise SystemExit(f"Ollama model {model!r} isn't available. Run: ollama pull {model}")
        for row_no, cells in rows:
            record = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
            note = record.get(header[obs], "")
            results[str(row_no)] = (await point(http, settings.ollama_url, model, record, note, settings.si_timeout_seconds) if use_si else
                                    {"status": "not assessed", "class": None, "id": None, "quote": None, "review": False, "candidates": candidates(note)})
            log.info("row %-4s test %-8s → %s", row_no, record.get(TARGET["test"], "?")[:8], results[str(row_no)]["class"] or results[str(row_no)]["status"])
    out = {"generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": model if use_si else None, "spec_hash": spec.spec_hash(),
           TARGET["investigation"]: {"table": TARGET["table"], "sha256": table["sha256"], "rows": results}}
    out_path.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Point at the sentence that states each BASS run's ignition outcome.")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--no-si", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    asyncio.run(run(settings.data_dir, settings.si_model, args.out or settings.data_dir / "outcome_evidence.json", not args.no_si))
