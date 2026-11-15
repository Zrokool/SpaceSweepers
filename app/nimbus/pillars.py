"""Pillar evidence: which of NASA's three fire-safety pillars does each investigation inform, shown with its own sentence.

Code finds candidate sentences, the Pillar pointer (SI) points at one per pillar or says none, and fixed rules
(P-1 to P-4 in Nimbus/agents/15-pillar-pointer.md) check the pointer. SI never writes a label or a score.

    python -m app.nimbus.pillars                       # every investigation, write data/pillar_evidence.json
    python -m app.nimbus.pillars --only PSI-69 PSI-102
    python -m app.nimbus.pillars --out /path/staging.json   # write elsewhere and leave the app's evidence alone
    python -m app.nimbus.pillars --no-si               # list the candidates only; nothing is pointed at
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

from app.analysis.attributes import load_vocabulary, term_pattern
from app.catalog import load_catalog
from app.config import get_settings
from app.nimbus import spec
from app.nimbus.method import sentences
from app.si import ollama

log = logging.getLogger("spacesweepers.pillars")

AGENT_FILE = "15-pillar-pointer.md"
PILLARS = ("prevention", "detection", "suppression")
FIELDS = (("impacts", "I"), ("objective", "O"), ("hypothesis", "H"), ("approach", "A"))   # in priority order
FIELD_OF = {prefix: field for field, prefix in FIELDS}
MAX_CANDIDATES = 6

PURPOSE = re.compile(r"\b(improv\w*|inform\w*|enabl\w*|help\w*|support\w*|provid\w*|develop\w*|design\w*|select\w*|screen\w*|determin\w*"
                     r"|quantif\w*|measur\w*|investigat\w*|stud(?:y|ies|ied)|evaluat\w*|characteri[sz]\w*|predict\w*|identif\w*"
                     r"|map\w*|assess\w*|reduc\w*|prevent\w*|detect\w*|suppress\w*|extinguish\w*|understand\w*|lead\w*"
                     r"|contribut\w*|valid\w*|aim\w*)\b", re.I)
OTHER_WORK = re.compile(r"\b(based on|builds? on|building on|previous(?:ly)?|earlier work)\b", re.I)
NEGATION = re.compile(r"\b(not|no|never|without|neither|nor)\b", re.I)


def numbered(inv: dict) -> dict[str, tuple[str, str]]:
    """{sentence id: (field, sentence)}: Research Impacts I1…, Objective O1…, Hypothesis H1…, Approach A1…"""
    out: dict[str, tuple[str, str]] = {}
    for field, prefix in FIELDS:
        out.update({f"{prefix}{n}": (field, s) for n, s in enumerate(sentences(inv.get(field) or ""), 1)})
    return out


def _cue_hit(text: str, cues: list[str], exclusions: list[str] = ()) -> bool:
    """A cue word is in the sentence and not negated (P-2). Phrases in `exclusions` ("smoke point") are ignored first."""
    for pattern in exclusions:
        text = re.sub(pattern, " ", text, flags=re.I)
    for cue in cues:
        for m in term_pattern(cue).finditer(text):
            before = text[max(0, m.start() - 40):m.start()].split()[-4:]
            if not NEGATION.search(" ".join(before)):
                return True
    return False


def is_candidate(field: str, text: str, cues: list[str], exclusions: list[str] = ()) -> bool:
    """P-1 to P-3 for one sentence and one pillar."""
    if not _cue_hit(text, cues, exclusions):
        return False
    if field == "impacts":                         # a Research Impacts sentence already states what the work is for
        return True
    return bool(PURPOSE.search(text)) and not OTHER_WORK.search(text)


def candidates(inv: dict, vocabulary: dict) -> dict[str, list[str]]:
    """The sentence ids code offers for each pillar, best field first, at most MAX_CANDIDATES."""
    ids = numbered(inv)
    out = {}
    for pillar in PILLARS:
        cues, skip = vocabulary["pillar_cues"][pillar], vocabulary.get("pillar_cue_exclusions", [])
        found = [sid for sid, (field, text) in ids.items() if is_candidate(field, text, cues, skip)]
        if any(ids[s][0] != "approach" for s in found):          # the Approach describes how a test is run; it is offered only when nothing else fits
            found = [s for s in found if ids[s][0] != "approach"]
        out[pillar] = found[:MAX_CANDIDATES]
    return out


def user_message(inv: dict, ids: dict, cands: dict[str, list[str]]) -> str:
    wanted = [sid for sid in ids if any(sid in v for v in cands.values())]
    return spec.agent(AGENT_FILE).user_template.format(
        id=inv["id"], title=inv["title"], project_type=f"{inv['project_type']} Investigation",
        sentences="\n".join(f"{sid}: {ids[sid][1]}" for sid in wanted) or "(none)",
        **{p: ", ".join(cands[p]) or "none" for p in PILLARS})


def decide(inv: dict, proposal: dict, vocabulary: dict) -> dict:
    """Turn SI's pointers into the stored entry. Code decides what is evidence."""
    ids, cands = numbered(inv), candidates(inv, vocabulary)
    out: dict = {}
    review = []
    for pillar in PILLARS:
        sid = str(proposal.get(pillar) or "none").strip().rstrip(":")
        if sid != "none" and sid in cands[pillar]:                      # P-1: only a candidate code found can be evidence
            field, text = ids[sid]
            out[pillar] = {"status": "evidence", "id": sid, "field": field, "quote": text}
        else:
            out[pillar] = {"status": "none", "id": None, "field": None, "quote": None}
            if cands[pillar]:
                review.append(f"{pillar}: SI pointed at none, but {', '.join(cands[pillar][:3])} contain a cue word.")
    return {**out, "review": review, "candidates": {p: cands[p] for p in PILLARS}, "proposed": {p: proposal.get(p) for p in PILLARS}}


NOT_APPLICABLE = {"status": "not applicable", "id": None, "field": None, "quote": None}


async def label_one(http: httpx.AsyncClient, url: str, model: str, inv: dict, vocabulary: dict, timeout: float) -> dict:
    if not inv["is_combustion"]:                                           # P-4
        return {**{p: dict(NOT_APPLICABLE) for p in PILLARS}, "review": [], "candidates": {}, "proposed": {},
                "reason": f"Not combustion research ({inv['research_area']})."}
    ids, cands = numbered(inv), candidates(inv, vocabulary)
    if not any(cands.values()):
        return {**decide(inv, {}, vocabulary), "model": None}
    agent = spec.agent(AGENT_FILE)
    schema = json.loads(json.dumps(agent.output_schema))
    for pillar in PILLARS:
        schema["properties"][pillar]["enum"] = [*cands[pillar], "none"]    # SI can only point at a candidate, or say none
    try:
        proposal = await ollama.chat_json(http, url, model, agent.system_prompt, user_message(inv, ids, cands), schema, timeout, agent.meta.get("options"))
    except ollama.SIError as e:
        return {**{p: {"status": "not assessed", "id": None, "field": None, "quote": None} for p in PILLARS}, "review": [],
                "candidates": cands, "proposed": {}, "reason": f"The SI model didn't answer: {e}"}
    return {**decide(inv, proposal, vocabulary), "model": model}


async def run(data_dir: Path, model: str, only: list[str] | None, out_path: Path, use_si: bool = True) -> dict:
    settings = get_settings()
    catalog = load_catalog(data_dir)
    vocabulary = load_vocabulary(data_dir / "vocabulary.yaml")
    existing = json.loads(out_path.read_text(encoding="utf-8"))["pillars"] if out_path.exists() else {}
    async with httpx.AsyncClient() as http:
        if use_si:
            installed = await ollama.installed_models(http, settings.ollama_url)
            if installed is None or not ollama.is_installed(model, installed):
                raise SystemExit(f"Ollama model {model!r} isn't available. Run: ollama pull {model}")
        for inv in catalog.ordered():
            if only and inv["id"] not in only:
                continue
            if use_si:
                existing[inv["id"]] = await label_one(http, settings.ollama_url, model, inv, vocabulary, settings.si_timeout_seconds)
            else:
                cands = candidates(inv, vocabulary)
                existing[inv["id"]] = {**{p: {"status": "not assessed", "id": None, "field": None, "quote": None} for p in PILLARS},
                                       "review": [], "candidates": cands, "proposed": {}}
            shown = ", ".join(p for p in PILLARS if existing[inv["id"]][p]["status"] == "evidence") or "none"
            log.info("%s %-14s → %s", inv["id"], inv["name"][:14], shown)
    result = {"generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": model if use_si else None, "spec_hash": spec.spec_hash(),
              "pillars": dict(sorted(existing.items(), key=lambda kv: int(kv[0].split("-")[1])))}
    out_path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Point at the sentence that shows each investigation informs a fire-safety pillar.")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--out", type=Path, help="write here instead of data/pillar_evidence.json")
    parser.add_argument("--no-si", action="store_true", help="candidates only; no model call")
    args = parser.parse_args()
    settings = get_settings()
    asyncio.run(run(settings.data_dir, settings.si_model, args.only, args.out or settings.data_dir / "pillar_evidence.json", not args.no_si))
