"""Micro-Flame: a short physical explanation of the Flame Sweeper patterns, checked by Nimbus.

How one explanation is made (spec: Nimbus/agents/14-micro-flame.md):

    code gathers evidence    computed patterns and the skill check (kind "C"), plus PSI document passages (kind "D")
    SI writes (Micro-Flame)  at most three sentences, each citing that evidence
    Nimbus checks            C-CITE, C-NUM, C-NAME, C-SCOPE, C-METHOD, C-MECH, C-QUOTE, C-SUPPORT, and C-ANCHOR
                             (every sentence must cite a computed pattern)
    result                   the kept sentences with numbered sources, the removed ones with the rule that removed them

If SI is offline nothing is invented: the patterns stand on their own.
"""

from __future__ import annotations

import json
import logging
from collections import OrderedDict
from dataclasses import asdict, dataclass, field

import httpx

from app.config import Settings
from app.insights.frame import reader_for
from app.insights.library import Item, Library
from app.insights.pipeline import ITEM_PROMPT_CHARS
from app.insights.report import source_entry
from app.insights.verify import Checker
from app.nimbus import spec
from app.nimbus.runtime import data_version, model_slot
from app.si import ollama

log = logging.getLogger(__name__)

AGENT_FILE = "14-micro-flame.md"
CACHE_SIZE = 32


@dataclass
class Explanation:
    """What the Flame Sweeper shows: the checked sentences, their sources, and what Nimbus removed."""
    mode: str = "offline"                                   # "si", "no_answer" (nothing verified) or "offline"
    answer: list[dict] = field(default_factory=list)        # [{"text", "cites": [display numbers]}]
    sources: list[dict] = field(default_factory=list)       # source cards, numbered as the answer cites them
    removed: list[dict] = field(default_factory=list)       # [{"text", "reason", "rules"}]
    notes: list[str] = field(default_factory=list)
    model: str | None = None
    cached: bool = False

    def as_dict(self) -> dict:
        return asdict(self)


class AnswerCache:
    """A small least-recently-used cache of finished explanations, so the same selection is never asked of the model twice."""

    def __init__(self, size: int = CACHE_SIZE) -> None:
        self._items: OrderedDict[tuple, Explanation] = OrderedDict()
        self._size = size

    def get(self, key: tuple) -> Explanation | None:
        if key in self._items:
            self._items.move_to_end(key)
            return self._items[key]
        return None

    def put(self, key: tuple, value: Explanation) -> None:
        self._items[key] = value
        while len(self._items) > self._size:
            self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


CACHE = AnswerCache()


def build_evidence(result: dict, library: Library) -> list[Item]:
    """Computed patterns first, then PSI document passages. Every item is something code found, never something SI wrote."""
    meta = spec.agent(AGENT_FILE).meta
    items = [Item(f"C:sweeper:{p['id']}", "C", "-", p["text"], "computed by code from the PSI test tables") for p in result["patterns"]]
    items.append(Item("C:sweeper:skill", "C", "-", result["skill"]["reason"], "computed by code (cross-validation)"))
    seen: set[str] = set()
    for query in meta["doc_queries"].get(result["family"], []):
        for hit in library.search(query, psi_ids=None, limit=3):
            if hit.kind == "D" and hit.id not in seen and len(seen) < meta["max_passages"]:
                seen.add(hit.id)
                items.append(hit)
    return items


def build_prompt(result: dict, evidence: list[Item]) -> str:
    lines = []
    for n, item in enumerate(evidence, 1):
        text = item.text if len(item.text) <= ITEM_PROMPT_CHARS else item.text[:ITEM_PROMPT_CHARS].rsplit(" ", 1)[0] + " …"
        lines.append(f"E{n}. [{'computed by code' if item.kind == 'C' else 'PSI document'}] {text}")
    return spec.agent(AGENT_FILE).user_template.format(family=result["label"], evidence="\n".join(lines))


async def explain(http: httpx.AsyncClient, settings: Settings, library: Library, checker: Checker, result: dict) -> Explanation:
    """Explain one Flame Sweeper result (the dict returned by `app.analysis.sweeper.sweep`)."""
    key = (result["family"], json.dumps(result["filters"], sort_keys=True), json.dumps(result["habitat"], sort_keys=True, default=str),
           data_version(settings))
    cached = CACHE.get(key)
    if cached is not None:
        return Explanation(**{**asdict(cached), "cached": True})
    out = Explanation(model=settings.si_model)
    installed = await ollama.installed_models(http, settings.ollama_url)
    if installed is None or not ollama.is_installed(settings.si_model, installed):
        out.notes.append("SI is not available, so no explanation was written. The patterns above stand on their own.")
        return out
    agent = spec.agent(AGENT_FILE)
    evidence = build_evidence(result, library)
    schema = json.loads(json.dumps(agent.output_schema))
    schema["properties"]["sentences"]["items"]["properties"]["cites"]["items"] = {"type": "integer", "minimum": 1, "maximum": len(evidence)}
    try:
        async with model_slot(settings.si_max_waiting, settings.si_queue_wait_seconds):
            raw = await ollama.chat_json(http, settings.ollama_url, settings.si_model, agent.system_prompt, build_prompt(result, evidence),
                                         schema, settings.si_timeout_seconds, agent.meta.get("options"), settings.si_keep_alive)
    except (ollama.SIError, httpx.HTTPError) as e:
        out.notes.append(f"The explanation could not be written ({e}).")
        return out
    frame = reader_for(library.catalog).read("Explain the Flame Sweeper patterns", [])
    verification = checker.verify(raw.get("sentences") or [], evidence, frame, anchor_kind=agent.meta["anchor_kind"])
    order: list[int] = []
    for sentence in verification.kept:
        order += [c for c in sentence["cites"] if c not in order]
    display = {e: n for n, e in enumerate(order, 1)}
    out.mode = "si" if verification.kept else "no_answer"
    out.answer = [{"text": s["text"], "cites": [display[c] for c in s["cites"]]} for s in verification.kept]
    out.sources = [source_entry(display[e], evidence[e - 1], library) for e in order]
    out.removed = [{"text": r.text, "reason": r.reason, "rules": r.rules} for r in verification.removed]
    if not verification.kept:
        out.notes.append("Nothing Micro-Flame wrote could be verified, so no explanation is shown. The PSI passages found did not support one.")
    if out.mode == "si":
        CACHE.put(key, out)
    return out
