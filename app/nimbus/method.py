"""Method labels: was each investigation Experimental, Simulation, or both?

SI never creates an experiment or a simulation and never writes a label. For each
investigation the Investigator (SI) is asked two questions and may only answer by
pointing at a numbered sentence from the PSI Approach or Objective:

    1. Which sentence shows the investigators ran their own physical tests?
    2. Which sentence shows the investigators ran their own computer model or simulation?

Fixed rules (V-METHOD in Nimbus/agents/10-investigator.md) then check each pointed-at
sentence. Code, not SI, decides the labels. An investigation can have both labels
(two separate labels, as for ACME CFI-G), one, or "Not classified" with the reason.

    python -m app.nimbus.method                        # label every investigation, write data/method_flags.json
    python -m app.nimbus.method --only PSI-117 PSI-98
    python -m app.nimbus.method --out /path/staging.json   # write somewhere else, leave the app's labels alone

The team can settle a label by hand in data/method_flags.yaml. The model is the app's
one SI model (setting SS_SI_MODEL, default granite3.3:2b).
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

from app.catalog import load_catalog
from app.config import get_settings
from app.nimbus import spec
from app.si import ollama

log = logging.getLogger("spacesweepers.method")

LABELS = {"experimental": "Experimental", "simulation": "Simulation"}
FLAGS = ("experimental", "simulation", "both", "unverified")     # `both` = the two separate labels together
MEASURED = ("experimental", "both")

# Cue words, checked inside the pointed-at sentence. A cue is necessary, never sufficient.
MODEL_CUE = re.compile(r"\b(CFD|OpenFOAM|numerical\w*|simulations?|simulated|computational\w*|model(?:s|ing|ling|ed|led)?"
                       r"|DNS|flamelet|Navier)\b", re.I)
PHYSICAL_CUE = re.compile(r"\b(experiments?|experimentally|tests?|tested|testing|conducted|performed|flight|aboard|ignit\w*"
                          r"|samples?|specimens?|crew|installed|measur\w*|cameras?|thermocouples?|radiometers?|observ\w*"
                          r"|dispens\w*|captur\w*|calibrat\w*|on-orbit|apparatus|hardware|burners?|glovebox|recorded|burn(?:ed|ing)?)\b", re.I)
# "simulating a large piece of fabric" describes a physical sample, not a computer simulation.
NOT_A_MODEL = re.compile(r"\b(simulating|emulat\w*|mimic\w*)\b", re.I)
REAL_PLATFORMS = re.compile(r"ISS|International Space Station|Cygnus|Shuttle", re.I)
# A Ground study built on another investigation's flight data (V-METHOD-3): words that show a test the
# investigators ran themselves, and words that show a sentence is about data that already existed.
OWN_TEST_CUE = re.compile(r"\b(experiments?|experimentally|tests?|tested|conducted|performed|aboard|crew|installed"
                          r"|measur\w*|cameras?|thermocouples?|radiometers?)\b", re.I)
REUSE_CUE = re.compile(r"\b(flight data|experimental data|experimental conditions|experimental imagery|data sets?"
                       r"|data (?:from|obtained)|obtained from|PSI|observations|validat\w*|compar\w*)\b", re.I)
# A sentence that only says models are to be validated or compared doesn't show the investigators ran one.
CHECKS_ONLY = re.compile(r"\b(validat\w*|compar\w*|agreement|agree\w*)\b", re.I)
_VERB = r"(?:develop\w*|perform\w*|conduct\w*|ut\w*ized|used?|using|simulated|support\w*|ran|run|created|built|coupled|pursue|implement\w*|employ\w*|generat\w*)"
# "aims to develop models", "goals include": a stated aim is not the investigators' own finished model or simulation.
AIM_ONLY = re.compile(r"\b(aims?|goals?|seeks?|hopes?)\b(?:\W+\w+){0,2}?\W+(?:to|include|includes)\b", re.I)
OWN_WORK = re.compile(rf"\b{_VERB}\b", re.I)
_MODEL = MODEL_CUE.pattern
# The verb has to be about the model itself: within a few words of it, not elsewhere in the sentence.
OWN_MODEL_WORK = re.compile(rf"\b(?:was|were)\W+(?:simulated|modell?ed)\b|\b{_VERB}\b(?:\W+\w+){{0,5}}?\W+(?:{_MODEL})|(?:{_MODEL})(?:\W+\w+){{0,5}}?\W+(?:(?:was|were|is|are|be|to)\W+)+{_VERB}\b", re.I)
# "By using the FLEX data from PSI, the purpose was to…": the opening clause is about existing data, the rest is the investigators' own work.
DATA_PREFIX = re.compile(r"^(?:By|Using|With)\b[^,]*,\s*", re.I)


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(])|\n+", text or "")
    return [" ".join(p.split()) for p in parts if len(p.strip()) >= 25]


def numbered(inv: dict) -> dict[str, tuple[str, str]]:
    """{sentence id: (field, sentence)} for the Approach (A1…) and Objective (O1…)."""
    out = {f"A{n}": ("approach", s) for n, s in enumerate(sentences(inv["approach"]), 1)}
    out.update({f"O{n}": ("objective", s) for n, s in enumerate(sentences(inv["objective"]), 1)})
    return out


def user_message(inv: dict, ids: dict[str, tuple[str, str]]) -> str:
    listing = lambda field: "\n".join(f"{k}: {s}" for k, (f, s) in ids.items() if f == field) or "(none)"  # noqa: E731
    return spec.agent("10-investigator.md").user_template.format(
        id=inv["id"], title=inv["title"], project_type=f"{inv['project_type']} Investigation",
        platform=inv["platform"] or "none", related=", ".join(inv["related"]) or "none",
        approach_sentences=listing("approach"), objective_sentences=listing("objective"))


def _has_model_cue(text: str) -> bool:
    return bool(MODEL_CUE.search(NOT_A_MODEL.sub(" ", text)))


def is_flown(inv: dict) -> bool:
    return inv["project_type"] == "Microgravity" and bool(REAL_PLATFORMS.search(inv["platform"] or ""))


# ------------------------------------------------------------------------------ the rules (no SI)
def check_physical(inv: dict, sid: str, ids: dict) -> tuple[bool, str]:
    """V-METHOD-1: does this sentence show the investigators' own physical test?"""
    if sid not in ids:
        return False, f"{sid!r} is not a sentence of this record."
    quote = ids[sid][1]
    if not PHYSICAL_CUE.search(quote):
        return False, f"{sid} has no physical-test word (experiment, test, measured, camera, sample…)."
    clause = DATA_PREFIX.sub("", quote)
    if _has_model_cue(clause):
        # Both kinds in one sentence ("conduct new simulations and ground-based experiments") only counts when a test
        # word is left once the modelling words are taken out, and the investigators' own verb is there.
        left = MODEL_CUE.sub(" ", NOT_A_MODEL.sub(" ", clause))
        if not (re.search(r"\b(experiments?|tests?|testing)\b", left, re.I) and OWN_WORK.search(clause)):
            return False, f"{sid} also describes modelling, so it can't by itself show a physical test."
    if inv["project_type"] == "Ground" and inv["uses_data_from"]:
        named = [n for n in inv.get("source_names", []) if re.search(rf"\b{re.escape(n)}\b", clause, re.I)]
        if not OWN_TEST_CUE.search(clause) or named or REUSE_CUE.search(clause):
            return False, (f"This ground investigation builds on flight data from {', '.join(inv['uses_data_from'])}; {sid} is about "
                           "that existing data, not a test the investigators ran themselves.")
    return True, f"{sid} describes physical testing."


def check_model(inv: dict, sid: str, ids: dict) -> tuple[str, str]:
    """V-METHOD-2: does this sentence show the investigators' own model or simulation?
    Returns ("yes" | "review" | "no", detail). "review" = a sentence about validating or comparing models: a person decides."""
    if sid not in ids:
        return "no", f"{sid!r} is not a sentence of this record."
    quote = ids[sid][1]
    if not _has_model_cue(quote):
        return "no", f"{sid} has no modelling word (CFD, simulation, numerical, model)."
    if AIM_ONLY.search(quote):
        return "review", f"{sid} states an aim to build models; it doesn't say the investigators ran one."
    plain = NOT_A_MODEL.sub(" ", quote)
    if CHECKS_ONLY.search(quote):
        plain = re.sub(r"\bto\s+(?:develop|use|create|build|generate)\w*", " ", plain, flags=re.I)   # "to validate … and to develop models" is a goal, not a run
    if not OWN_MODEL_WORK.search(plain):
        if CHECKS_ONLY.search(quote):
            return "review", f"{sid} only says models are validated or compared; it doesn't say the investigators ran one."
        return "no", f"{sid} mentions modelling but doesn't say the investigators built or ran a model."
    return "yes", f"{sid} describes the investigators' own modelling."


def own_sentences(inv: dict, ids: dict, kind: str) -> list[str]:
    """Sentences code can see that would pass the rule for `kind`, used to flag what SI did not point at."""
    out = []
    for sid in ids:
        if kind == "physical":
            if check_physical(inv, sid, ids)[0]:
                out.append(sid)
        elif check_model(inv, sid, ids)[0] == "yes":
            out.append(sid)
    return out


def decide(inv: dict, proposal: dict, ids: dict) -> dict:
    """Turn SI's two pointers into the stored entry. Code decides every label."""
    phys_id, model_id = (str(proposal.get(k) or "none").strip().rstrip(":") for k in ("physical_evidence", "model_evidence"))
    checks: list[dict] = []
    review: list[str] = []
    flown = is_flown(inv)
    entry = {"experimental": None, "simulation": None}

    # ---- Experimental
    if phys_id != "none":
        ok, detail = check_physical(inv, phys_id, ids)
        checks.append({"rule": "V-METHOD-1", "ok": ok, "detail": detail})
        if ok:
            entry["experimental"] = {"id": phys_id, "field": ids[phys_id][0], "quote": ids[phys_id][1], "basis": "sentence"}
    if entry["experimental"] is None and flown:
        why = f"PSI lists a Microgravity investigation flown on {inv['platform']}."
        checks.append({"rule": "V-METHOD-3", "ok": True, "detail": why + " Flown hardware means physical tests."})
        entry["experimental"] = {"id": None, "field": None, "quote": None, "basis": why}
    elif entry["experimental"] is None and phys_id == "none":
        missed = own_sentences(inv, ids, "physical")
        if missed:
            review.append(f"Experimental: SI pointed at no sentence, but {', '.join(missed[:3])} may describe the investigators' own tests.")
            checks.append({"rule": "V-METHOD-4", "ok": False, "detail": review[-1]})

    # ---- Simulation
    if model_id != "none":
        verdict, detail = check_model(inv, model_id, ids)
        checks.append({"rule": "V-METHOD-2", "ok": verdict == "yes", "detail": detail})
        if verdict == "yes":
            entry["simulation"] = {"id": model_id, "field": ids[model_id][0], "quote": ids[model_id][1], "basis": "sentence"}
        elif verdict == "review":
            review.append(f"Simulation: {detail} ({ids[model_id][1]!r})")
    else:
        missed = own_sentences(inv, ids, "model")
        if missed:
            review.append(f"Simulation: SI pointed at no sentence, but {', '.join(missed[:3])} may describe the investigators' own modelling.")
            checks.append({"rule": "V-METHOD-4", "ok": False, "detail": review[-1]})

    labels = [LABELS[k] for k in ("experimental", "simulation") if entry[k]]
    flag = {0: "unverified", 1: None, 2: "both"}[len(labels)] or labels[0].lower()
    failed = [c["detail"] for c in checks if not c["ok"]]
    reason = None
    if not labels:
        reason = " ".join(failed + review) or "No sentence in the Approach or Objective shows the investigators' own physical test or simulation."
    return {"flag": flag, "labels": labels, "status": "verified" if labels else "unverified", "measured": bool(entry["experimental"]),
            "experimental": entry["experimental"], "simulation": entry["simulation"],
            "review": review, "reason": reason, "checks": checks,
            "proposed": {"physical_evidence": phys_id, "model_evidence": model_id}}


async def propose(http: httpx.AsyncClient, url: str, model: str, inv: dict, ids: dict, timeout: float,
                  feedback: str | None = None) -> dict:
    agent = spec.agent("10-investigator.md")
    schema = json.loads(json.dumps(agent.output_schema))
    for key in ("physical_evidence", "model_evidence"):
        schema["properties"][key]["enum"] = [*ids, "none"]       # SI can only point at a real sentence, or say none
    user = user_message(inv, ids) + (f"\n\n{feedback}" if feedback else "")
    return await ollama.chat_json(http, url, model, agent.system_prompt, user, schema, timeout, agent.meta.get("options"))


async def label_one(http: httpx.AsyncClient, url: str, model: str, inv: dict, timeout: float) -> dict:
    ids = numbered(inv)
    if not ids:
        return {"flag": "unverified", "labels": [], "status": "unverified", "measured": False, "experimental": None, "simulation": None,
                "review": [], "checks": [], "reason": "The record has no Approach or Objective text."}
    try:
        proposal = await propose(http, url, model, inv, ids, timeout)
        result = decide(inv, proposal, ids)
        failed = [c for c in result["checks"] if not c["ok"]]
        if failed:
            # One second chance, only about the question that failed. The revised pointer goes through the same rules.
            # Facts only: which sentences pass the rule. SI still has to point at one, and the same rules check it again.
            hints = []
            about = lambda kind, n: any(c["rule"] == f"V-METHOD-{n}" or (c["rule"] == "V-METHOD-4" and c["detail"].startswith(kind)) for c in failed)  # noqa: E731
            if about("Experimental", 1):
                hints.append("Sentences that describe the investigators' own physical testing: " + (", ".join(own_sentences(inv, ids, "physical")) or "none") + ".")
            if about("Simulation", 2):
                hints.append("Sentences that describe the investigators' own modelling: " + (", ".join(own_sentences(inv, ids, "model")) or "none") + ".")
            feedback = ("A check failed on your answer: " + " ".join(c["detail"] for c in failed) + " "
                        + " ".join(hints) + " Read the sentences again and answer once more.")
            second = decide(inv, await propose(http, url, model, inv, ids, timeout, feedback), ids)
            second["attempts"] = [result["proposed"], second["proposed"]]
            if len(second["labels"]) >= len(result["labels"]) and len([c for c in second["checks"] if not c["ok"]]) <= len(failed):
                result = second
            else:
                result["attempts"] = second["attempts"]
    except ollama.SIError as e:
        return {"flag": "unverified", "labels": [], "status": "not assessed", "measured": False, "experimental": None, "simulation": None,
                "review": [], "checks": [], "reason": f"The SI model didn't answer: {e}"}
    return {**result, "model": model}


async def run(data_dir: Path, model: str, only: list[str] | None, out_path: Path | None = None) -> dict:
    settings = get_settings()
    catalog = load_catalog(data_dir)
    out_path = out_path or data_dir / "method_flags.json"
    existing = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {"flags": {}}
    flags = existing["flags"]
    async with httpx.AsyncClient() as http:
        installed = await ollama.installed_models(http, settings.ollama_url)
        if installed is None or not ollama.is_installed(model, installed):
            raise SystemExit(f"Ollama model {model!r} isn't available. Run: ollama pull {model}")
        for inv in catalog.ordered():
            if only and inv["id"] not in only:
                continue
            flags[inv["id"]] = await label_one(http, settings.ollama_url, model, inv, settings.si_timeout_seconds)
            f = flags[inv["id"]]
            log.info("%s %-14s → %-26s %s", inv["id"], inv["name"][:14], " + ".join(f["labels"]) or "Not classified", f["reason"] or "")
    result = {"generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "model": model,
              "spec_hash": spec.spec_hash(), "flags": dict(sorted(flags.items(), key=lambda kv: int(kv[0].split("-")[1])))}
    out_path.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    parser = argparse.ArgumentParser(description="Label each investigation Experimental, Simulation, or both.")
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--out", type=Path, help="write here instead of data/method_flags.json")
    args = parser.parse_args()
    settings = get_settings()
    asyncio.run(run(settings.data_dir, settings.si_model, args.only, args.out))
