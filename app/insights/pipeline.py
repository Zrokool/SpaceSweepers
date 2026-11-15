"""The SI Insights pipeline: one question in, a stream of stage events and a checked report out.

    read the question (code) → Investigator chooses tools (SI) → tools run (code) →
    Analyst writes (SI) → Nimbus checks every sentence (code) → report (code) → run log

If Ollama is down or the model fails, the answer falls back to the evidence alone ("sources only").
Only one model call runs at a time.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from app.config import Settings
from app.insights import answers, hygiene
from app.insights.frame import Frame, reader_for
from app.insights.library import KIND_LABEL, Item, Library
from app.insights.report import build_report, source_entry, structured
from app.insights.tools import TOOL_MENU, ToolCall, ToolError, Toolbox
from app.insights.verify import Checker
from app.nimbus import spec
from app.nimbus.runtime import data_version, model_slot
from app.si import ollama

log = logging.getLogger(__name__)

MAX_EVIDENCE_ITEMS = 12
PROMPT_CHARS = 8_000           # about 1,300 words of evidence: a CPU runs this model slowly, so the prompt stays small
CHOOSE_TOKENS = 160            # the Investigator's reply is a few tool calls; it never needs more
ITEM_PROMPT_CHARS = 900
TIER = {"C": 0, "M": 0, "L": 0, "S": 0, "I": 1, "A": 1, "F": 1, "R": 2, "T": 2, "D": 2, "P": 2, "V": 2}
DIRECT_INTENTS = {"count", "list", "lineage", "files"}      # questions whose answer is a number or a list that code already computes
CACHE_SIZE = 64
_cache: "OrderedDict[tuple, list[dict]]" = OrderedDict()   # finished answers, as the events that made them, until the data or the model changes
DRAFT_TEXT = re.compile(r'"text"\s*:\s*"((?:[^"\\]|\\.)*)"')


def sse(event: dict) -> bytes:
    return f"data: {json.dumps(event)}\n\n".encode()


def needs_investigator(frame: Frame) -> bool:
    """The Investigator (SI) only helps with open questions. When the question names an investigation or asks for a
    count, list, comparison, lineage, files, tests or publications, code's own calls already cover it, so the model
    call (5 to 30 s warm, minutes when the model is busy) is skipped."""
    return not (frame.psi_ids or frame.intents)


def direct_answer(frame: Frame, evidence: list[Item]) -> list[dict] | None:
    """Sentences written by code, straight from computed evidence, for questions that are just a count or a list.

    Returns None when the question needs reading and writing (then the Analyst, SI, answers and Nimbus checks it).
    """
    if not frame.intents or not set(frame.intents) <= DIRECT_INTENTS:
        return None
    picks: list[int] = []
    if "count" in frame.intents or ("list" in frame.intents and (frame.project_type or frame.methods) and not frame.psi_ids) \
            or ("lineage" in frame.intents and not frame.psi_ids):
        picks = [n for n, e in enumerate(evidence, 1) if e.id.startswith("C:count:")]
    elif "lineage" in frame.intents and frame.psi_ids:
        picks = [n for n, e in enumerate(evidence, 1) if e.kind == "L" and e.psi in frame.psi_ids]
    elif "files" in frame.intents and frame.psi_ids:
        picks = [n for n, e in enumerate(evidence, 1) if e.kind == "F" and e.psi in frame.psi_ids]
    out = []
    for n in picks[:3]:
        text = evidence[n - 1].text
        out.append({"text": text if len(text) <= 700 else text[:700].rsplit(" ", 1)[0] + " …", "cites": [n]})
    return out or None


def draft_sentences(buffer: str) -> list[str]:
    """The sentences the model has finished writing so far, read from its partly written JSON."""
    out = []
    for m in DRAFT_TEXT.finditer(buffer):
        try:
            out.append(json.loads(f'"{m.group(1)}"'))
        except ValueError:
            continue
    return out


# ------------------------------------------------------------------ tools: code's own calls, then the Investigator's
def baseline_calls(frame: Frame, toolbox: Toolbox) -> list[ToolCall]:
    """Calls code always makes from the question alone, so the answer never depends on the model choosing well."""
    raw: list[dict] = []
    ids = frame.psi_ids[:3]
    query = frame.search_text
    raw.append({"tool": "search_library", "psi_ids": ids, "query": query})
    raw += [{"tool": "get_investigation", "psi_ids": [i]} for i in ids]
    reuse = "lineage" in frame.intents and not ids            # "how many ground studies reuse flight data?": the count must honour that condition
    if "count" in frame.intents or reuse or (frame.project_type or frame.methods) and not ids and ("list" in frame.intents or "count" in frame.intents):
        raw.append({"tool": "count_investigations", "type": frame.project_type, "method": frame.methods[0] if frame.methods else None,
                    "fuel_class": frame.fuel_class, "query": " ".join(frame.topics[:1]), "reuses_flight_data": True if reuse else None})
    if "compare" in frame.intents and len(ids) >= 2:
        raw.append({"tool": "compare", "psi_ids": ids})
    if "lineage" in frame.intents and ids:
        raw.append({"tool": "get_lineage", "psi_ids": ids})
    if frame.o2 or frame.pressure or frame.fuels or "tests" in frame.intents:
        o2, p = frame.o2 or {}, frame.pressure or {}
        raw.append({"tool": "find_tests", "psi_ids": ids, "query": query if not (frame.o2 or frame.pressure) else " ".join(frame.fuels),
                    "fuel": frame.fuels[0] if frame.fuels else None, "o2_min": o2.get("min"), "o2_max": o2.get("max"),
                    "pressure_min": p.get("min"), "pressure_max": p.get("max")})
        for i in ids[:2]:
            raw.append({"tool": "get_test_stats", "psi_ids": [i]})
    if "publications" in frame.intents and ids:
        raw.append({"tool": "get_publications", "psi_ids": ids[:2], "query": query})
    if "files" in frame.intents and ids:
        raw.append({"tool": "list_files", "psi_ids": ids})
    if frame.topics or "files" in frame.intents:
        raw.append({"tool": "search_documents", "psi_ids": ids, "query": query})
    out = []
    for r in raw:
        try:
            out.append(toolbox.check({k: v for k, v in r.items() if v not in (None, "", [])}))
        except ToolError:
            continue
    return out


def _investigation_lines(library: Library) -> str:
    return "\n".join(f"{i['id']} {i['name']}: {i['title'][:90]}" for i in library.catalog.ordered())


async def investigator_calls(http: httpx.AsyncClient, settings: Settings, frame: Frame, toolbox: Toolbox,
                             library: Library) -> list[ToolCall]:
    """Step 2 (SI): ask Granite which tools to call. Only validated calls come back."""
    agent = spec.agent("10-investigator.md")
    system = spec.block("10-investigator.md", "Chat: system prompt", "text").replace(
        "{tools}", "\n".join(f"- {name}: {desc}" for name, desc in TOOL_MENU.items()))
    template = spec.block("10-investigator.md", "Chat: user message template", "text")
    schema = json.loads(spec.block("10-investigator.md", "Chat: output schema", "json"))
    item = schema["properties"]["calls"]["items"]["properties"]
    item["tool"]["enum"] = list(TOOL_MENU)
    item["psi_ids"]["items"]["enum"] = sorted(toolbox.ids)
    names = {i["id"]: i["name"] for i in library.catalog.ordered()}
    mentions = "; ".join(f"{c['kind']}: {c['label']}" for c in frame.chips(names)) or "nothing specific"
    # The list of investigations only helps when the question names none; otherwise code has already resolved the names.
    listing = "" if frame.psi_ids else "The investigations (psi_id, name: title):\n" + _investigation_lines(library) + "\n"
    user = template.format(question=frame.question, mentions=mentions, investigations=listing)
    data = await ollama.chat_json(http, settings.ollama_url, settings.si_model, system, user, schema, settings.si_timeout_seconds,
                                  {**(agent.meta.get("options") or {}), "num_predict": CHOOSE_TOKENS}, settings.si_keep_alive)
    out = []
    for raw in (data.get("calls") or [])[:3]:
        if isinstance(raw, dict):
            try:
                out.append(toolbox.check(raw))
            except ToolError:
                continue
    return out


def gather(calls: list[ToolCall], toolbox: Toolbox) -> tuple[list[Item], list[dict]]:
    """Run the calls and assemble the numbered evidence list within the prompt budget."""
    results: list[Item] = []
    log_rows = []
    seen_labels = set()
    for call in calls:
        if call.label() in seen_labels:
            continue
        seen_labels.add(call.label())
        try:
            items = toolbox.run(call)
            log_rows.append({"call": call.label(), "items": [i.id for i in items]})
            results += items
        except ToolError as e:
            log_rows.append({"call": call.label(), "error": str(e)})
    unique: dict[str, Item] = {}
    for it in results:
        unique.setdefault(it.id, it)
    ordered = sorted(unique.values(), key=lambda it: TIER[it.kind])      # stable: relevance order kept within a tier
    evidence, used = [], 0
    for it in ordered:
        size = min(len(it.text), ITEM_PROMPT_CHARS)
        if evidence and (len(evidence) >= MAX_EVIDENCE_ITEMS or used + size > PROMPT_CHARS):
            continue
        evidence.append(it)
        used += size
    return evidence, log_rows


def evidence_text(evidence: list[Item]) -> str:
    lines = []
    for n, it in enumerate(evidence, 1):
        text = it.text if len(it.text) <= ITEM_PROMPT_CHARS else it.text[:ITEM_PROMPT_CHARS].rsplit(" ", 1)[0] + " …"
        lines.append(f"E{n}. [{KIND_LABEL[it.kind] if it.kind in KIND_LABEL else 'computed by code'}] {text}")
    return "\n".join(lines)


async def analyst_stream(http: httpx.AsyncClient, settings: Settings, frame: Frame, evidence: list[Item], library: Library):
    """Yields ("draft", sentences so far) while the model writes, then ("done", the parsed answer)."""
    agent = spec.agent("12-analyst.md")
    schema = json.loads(json.dumps(agent.output_schema))
    schema["properties"]["sentences"]["items"]["properties"]["cites"]["items"] = {"type": "integer", "minimum": 1, "maximum": len(evidence)}
    names = {i["id"]: i["name"] for i in library.catalog.ordered()}
    about = ("The question is about: " + ", ".join(f"{names[i]} ({i})" for i in frame.psi_ids) + ".\n") if frame.psi_ids else ""
    user = agent.user_template.format(question=frame.question, about=about, evidence=evidence_text(evidence))
    async for kind, payload in ollama.chat_json_stream(http, settings.ollama_url, settings.si_model, agent.system_prompt, user, schema,
                                                       settings.si_timeout_seconds, agent.meta.get("options"), settings.si_keep_alive):
        yield ("draft", draft_sentences(payload)) if kind == "chunk" else ("done", payload)


# ------------------------------------------------------------------ the run
def _write_log(settings: Settings, run_id: str, record: dict) -> None:
    try:
        settings.runs_dir.mkdir(parents=True, exist_ok=True)
        (settings.runs_dir / f"insights-{run_id}.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    except OSError as e:
        log.warning("could not write the SI Insights run log: %s", e)


async def run(*, question: str, previous: list[str], http: httpx.AsyncClient, settings: Settings, library: Library,
              toolbox: Toolbox, checker: Checker, habitat: dict | None = None) -> AsyncIterator[bytes]:
    """The same question on the same data and model replays its earlier checked answer instead of asking the model again."""
    key = (re.sub(r"\W+", " ", question.lower()).strip(), tuple(previous), habitat and habitat["key"], data_version(settings))
    if key in _cache:
        _cache.move_to_end(key)
        for ev in _cache[key]:
            if ev["type"] == "report":
                ev = {**ev, "report": {**ev["report"], "cached": True,
                                       "notes": [*ev["report"]["notes"], "Answered earlier from this same question; the data and model haven't changed."]}}
            yield sse(ev)
        return
    events: list[dict] = []
    async for chunk in _run(question=question, previous=previous, http=http, settings=settings, library=library, toolbox=toolbox, checker=checker, habitat=habitat):
        ev = json.loads(chunk[6:])
        if ev["type"] != "draft":
            events.append(ev)
        yield chunk
    report = next((e["report"] for e in events if e["type"] == "report"), None)
    if report and report["mode"] in ("si", "computed"):          # only answers that were checked, or computed by code, are kept
        _cache[key] = events
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)


async def _run(*, question: str, previous: list[str], http: httpx.AsyncClient, settings: Settings, library: Library,
               toolbox: Toolbox, checker: Checker, habitat: dict | None = None) -> AsyncIterator[bytes]:
    started = time.time()
    now = datetime.now(UTC)
    run_id = f"{now:%Y%m%d-%H%M%S}-{hashlib.sha1(question.encode()).hexdigest()[:6]}"
    reader = reader_for(library.catalog)
    names = {i["id"]: i["name"] for i in library.catalog.ordered()}
    record: dict = {"run_id": run_id, "question": question, "model": settings.si_model, "spec_hash": spec.spec_hash(), "stages": []}
    timings: dict[str, float] = {}
    last_draft: list[str] = []

    def stage(name: str, status: str, detail: str = "") -> bytes:
        record["stages"].append({"stage": name, "status": status, "detail": detail, "at": round(time.time() - started, 1)})
        return sse({"type": "stage", "stage": name, "status": status, "detail": detail})

    # 1. read the question (code)
    frame = reader.read(question, previous)
    record["frame"] = {k: v for k, v in frame.__dict__.items()}
    yield sse({"type": "frame", "chips": frame.chips(names)})
    yield stage("read", "done", "Read the question")

    # SI available?
    installed = await ollama.installed_models(http, settings.ollama_url)
    si_ok = installed is not None and ollama.is_installed(settings.si_model, installed)
    notes: list[str] = []
    if not si_ok:
        notes.append("SI offline: showing the evidence only." if installed is None else
                     f"Model {settings.si_model} isn't installed (ollama pull {settings.si_model}): showing the evidence only.")

    # 2. the Investigator chooses tools (SI), on top of code's own calls
    special = answers.build(frame, library.catalog, habitat)            # code's own answers: safety stance, coverage, habitat reference
    calls = baseline_calls(frame, toolbox)
    call_labels = [{"label": c.label(), "source": "code"} for c in calls]
    if si_ok and (special.direct or not needs_investigator(frame)):
        yield stage("investigator", "skipped", "The question is clear, so code chose the tools")
    elif si_ok:
        yield stage("investigator", "running", "The Investigator is choosing tools")
        t0 = time.time()
        try:
            async with model_slot(settings.si_max_waiting, settings.si_queue_wait_seconds):
                chosen = await investigator_calls(http, settings, frame, toolbox, library)
            timings["investigator"] = round(time.time() - t0, 1)
            known = {c.label() for c in calls}
            for c in chosen:
                if c.label() not in known:
                    calls.append(c)
                    call_labels.append({"label": c.label(), "source": "investigator"})
            yield stage("investigator", "done", f"{len(chosen)} tool call(s) chosen")
        except (ollama.SIError, httpx.HTTPError) as e:
            notes.append(f"The Investigator didn't answer ({e}); only code's own searches were used.")
            yield stage("investigator", "skipped", "Using code's own searches")
    record["calls"] = call_labels

    # 3. tools run (code)
    yield stage("tools", "running", "Looking up PSI data")
    evidence, tool_log = await asyncio.to_thread(gather, calls, toolbox)
    evidence, held = hygiene.scrub_evidence(evidence)
    if held:
        log.warning("held back %d passage(s) with instruction-like text: %s", len(held), [h["id"] for h in held])
        notes.append(f"{len(held)} PSI passage{'s were' if len(held) != 1 else ' was'} left out of the prompt because {'they' if len(held) != 1 else 'it'} contained instruction-like text.")
        record["held_back"] = held
    if special.only:
        evidence = special.items
    elif special.items:
        evidence = [*special.items, *evidence][:MAX_EVIDENCE_ITEMS]
    record["tools"], record["evidence"] = tool_log, [{"n": n, "id": e.id, "text": e.text} for n, e in enumerate(evidence, 1)]
    failed = {row["call"] for row in tool_log if "error" in row}
    call_labels = [c for c in call_labels if c["label"] not in failed]          # only tools that ran are shown
    ran = [c for c in calls if c.label() not in failed]
    yield sse({"type": "tools", "calls": call_labels})
    yield sse({"type": "evidence", "sources": [dict(source_entry(n, e, library), text=e.text[:300]) for n, e in enumerate(evidence, 1)]})
    yield stage("tools", "done", f"{len(evidence)} pieces of evidence")

    # 4–5. the Analyst writes (SI), Nimbus checks every sentence (code)
    verification, mode, raw = None, "sources_only", None
    direct = special.direct or (direct_answer(frame, evidence) if evidence else None)
    if direct:                                             # a count or a list: code writes it from the data, no SI, nothing to check
        mode = "computed"
        notes.append("Answered directly from the PSI data by code. No SI was needed.")
        yield stage("analyst", "skipped", "Computed by code")
    elif evidence and si_ok:
        yield stage("analyst", "running", "The Analyst is writing")
        t0 = time.time()
        try:
            async with model_slot(settings.si_max_waiting, settings.si_queue_wait_seconds):
                async for kind, payload in analyst_stream(http, settings, frame, evidence, library):
                    if kind == "draft":
                        if payload and payload != last_draft:
                            last_draft = payload
                            yield sse({"type": "draft", "sentences": payload})
                    else:
                        raw = payload
            timings["analyst"] = round(time.time() - t0, 1)
            yield stage("analyst", "done", "Answer drafted")
            yield stage("nimbus", "running", "Nimbus is checking every sentence")
            verification = await asyncio.to_thread(checker.verify, raw.get("sentences") or [], evidence, frame)
            mode = "si" if verification.kept else "no_answer"
            yield stage("nimbus", "done", f"{len(verification.kept)} verified · {len(verification.removed)} removed")
        except (ollama.SIError, httpx.HTTPError) as e:
            notes.append(f"The Analyst didn't answer ({e}).")
            yield stage("analyst", "skipped", "Showing the evidence only")
    elif not evidence:
        mode = "no_answer"
        yield stage("analyst", "skipped", "No evidence found")

    # 6. report (code)
    report = build_report(question=question, frame=frame, calls=call_labels, evidence=evidence, verification=verification,
                          library=library, mode=mode, model=settings.si_model if si_ok else None, notes=notes, run_id=run_id, direct=direct)
    report.update(structured(ran, toolbox, library))
    report["links"] = answers.links(frame, special)
    report["facts"] = None if report.get("table") else answers.facts(frame, library.catalog)
    report["habitat"] = special.habitat if special.habitat and any(i.id.startswith("C:habitat:") for i in evidence) else None
    record.update({"raw_answer": raw, "verification": None if verification is None else {
        "kept": verification.kept, "removed": [r.__dict__ for r in verification.removed], "checked": verification.checked},
        "mode": mode, "notes": notes, "seconds": {**timings, "total": round(time.time() - started, 1)}})
    await asyncio.to_thread(_write_log, settings, run_id, record)
    yield sse({"type": "report", "report": report})
    yield sse({"type": "done"})
