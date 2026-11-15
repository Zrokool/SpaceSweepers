"""The SI Insights report: what the user sees after Nimbus has checked an answer. Built by code (no SI).

Only sentences that passed every check appear as the answer, each with the sources it cites,
renumbered 1, 2, 3 in the order they are first used. Removed sentences are listed with the rule
that removed them. "What the data doesn't cover" is computed by code from what was and wasn't found.
"""

from __future__ import annotations

import re

from app.analysis import compare as compare_mod
from app.catalog import Catalog
from app.insights.frame import CASE_SENSITIVE, TOPICS, Frame
from app.insights.library import Item, Library
from app.insights.verify import DOI, QUOTED, _norm, number_supported, numbers_in

EXCERPT_CHARS = 1500
NO_ANSWER = "I couldn't find an answer in the PSI data that I could verify."


def _topic_present(topic: str, evidence: list[Item]) -> bool:
    for word in TOPICS[topic]:
        flags = 0 if word in CASE_SENSITIVE else re.I
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(word)}(?![A-Za-z0-9])", flags)
        if any(pattern.search(i.text) for i in evidence):
            return True
    return False


def not_covered(frame: Frame, evidence: list[Item], catalog: Catalog) -> list[str]:
    out = []
    for topic in frame.topics:
        if topic not in ("pressure",) and not _topic_present(topic, evidence):
            out.append(f"No PSI evidence about {topic} turned up for this question.")
    if frame.o2 or frame.pressure or frame.fuels or any(i.id.startswith("C:find_tests") for i in evidence):
        unmapped = [i for i in catalog.ordered() if i["is_combustion"] and not i["stats"] and i["tables"]]
        mapped = sum(1 for i in catalog.ordered() if i["stats"])
        out.append(f"Test tables can only be searched by number where their columns are mapped ({mapped} investigations so far); "
                   f"{len(unmapped)} other investigations' tables are searchable as text only. A missing match is not proof "
                   "that conditions were never tested.")
    named = [catalog.get(i) for i in frame.psi_ids if catalog.get(i)]
    shown_rows = {i.psi for i in evidence if i.kind == "T"}
    for inv in named:
        if inv["tables"] and not inv["stats"] and ("tests" in frame.intents or inv["id"] in shown_rows):
            out.append(f"{inv['name']}'s test table is downloaded, but its columns aren't mapped to units yet: its values appear as raw rows, "
                       "not as computed ranges or counts.")
        m = inv["method"]
        if m["status"] not in ("verified", "team-confirmed"):
            out.append(f"{inv['name']}: whether it was experimental or a simulation is not confirmed.")
        unread = [d for d in inv["documents"] if d["status"] != "read"]
        if unread:
            reasons = sorted({d["status"].replace("not read: ", "") for d in unread})
            out.append(f"{inv['name']}: {len(unread)} document(s) were not read ({'; '.join(reasons)}).")
        if not inv["is_combustion"]:
            out.append(f"{inv['name']} is not combustion research; it is in PSI's combustion search only because it {inv['match_reason']}.")
    if "partial gravity" in frame.question.lower() or re.search(r"\b(moon|lunar|mars|martian)\b", frame.question, re.I):
        out.append("PSI has no combustion data at Moon or Mars gravity yet; microgravity and normal-gravity results can only bound it.")
    return list(dict.fromkeys(out))[:6]


def followups(frame: Frame, catalog: Catalog) -> list[dict]:
    names = {i["id"]: i["name"] for i in catalog.ordered()}
    asked = set(frame.intents)
    out = []
    if len(frame.psi_ids) >= 2 and "compare" not in asked:
        a, b = (names[i] for i in frame.psi_ids[:2])
        out.append({"label": f"Compare {a} and {b}", "question": f"Compare {a} and {b}"})
    for psi_id in frame.psi_ids[:1]:
        n = names[psi_id]
        if not frame.methods:
            out.append({"label": f"Is {n} experimental or a simulation?", "question": f"Is {n} experimental or a simulation?"})
        if "files" not in asked:
            out.append({"label": f"Which documents does PSI hold for {n}?", "question": f"Which documents does PSI hold for {n}?"})
        if "publications" not in asked:
            out.append({"label": f"Show the publications for {n}", "question": f"Show the publications for {n}"})
        if "lineage" not in asked:
            out.append({"label": f"Which investigations use {n}'s data?", "question": f"Which investigations use {n}'s data?"})
    if not frame.psi_ids:
        for topic in frame.topics[:1]:
            out.append({"label": f"Which investigations mention {topic}?", "question": f"Which investigations mention {topic}?"})
        out += [{"label": "How many ground studies reuse flight data?", "question": "How many ground studies reuse flight data?"},
                {"label": "Which investigations were simulations?", "question": "Which investigations were simulations?"}]
    asked = re.sub(r"\W+", " ", frame.question.lower()).strip()
    out = [f for f in out if re.sub(r"\W+", " ", f["question"].lower()).strip() != asked]      # never suggest the question just asked
    return out[:3]


def source_entry(n: int, item: Item, library: Library) -> dict:
    src = library.source(item)
    computed = item.kind == "C"
    return {"n": n, "id": item.id, "label": f"{src['name']} · {item.where}" if not computed else "Computed by code from the PSI snapshot",
            "kind": src["kind_label"], "psi": None if computed else item.psi, "doi": src["doi"], "url": src["url"],
            "file": item.file, "page": item.page, "row": item.row, "computed": computed,
            "text": item.text[:EXCERPT_CHARS]}


def source_checks(texts: list[str], item: Item, library: Library) -> list[str]:
    """What Nimbus confirmed about one source: which numbers, names and quotes in the sentences that cite it are really in it."""
    if item.kind == "C":
        return ["Computed by code from the PSI snapshot, not written by SI"]
    out = []
    evidence_numbers = [x for x, _ in numbers_in(item.text)]
    seen: set[float] = set()
    for t in texts:
        for value, unit in numbers_in(t):
            if value not in seen and number_supported(value, unit, evidence_numbers):
                seen.add(value)
        for m in QUOTED.finditer(t):
            if _norm(m.group(1)) in _norm(item.text):
                out.append("quoted words are word for word in this source")
    if seen:
        out.insert(0, "numbers found in this source: " + ", ".join(f"{v:g}" for v in sorted(seen)))
    name = library.catalog.get(item.psi)["name"] if item.psi and library.catalog.get(item.psi) else None
    if name and any(name in t for t in texts):
        out.append(f"{name} is the investigation this source belongs to")
    return list(dict.fromkeys(out))


def structured(calls, toolbox, library: Library) -> dict:
    """A side-by-side table and a counted list, built by code from the tool calls that ran. No SI."""
    out: dict = {}
    catalog = library.catalog
    for c in calls:
        if c.tool == "compare" and len(c.psi_ids) >= 2 and "table" not in out:
            result = compare_mod.compare(catalog, c.psi_ids)
            out["table"] = {"title": "Side by side (computed by code from the records)",
                            "columns": [{"psi": i["id"], "name": i["name"]} for i in result["investigations"]],
                            "rows": [{"attribute": r["attribute"], "cells": r["cells"], "all_same": r["all_same"]} for r in result["attributes"]]}
        if c.tool == "count_investigations" and "list" not in out:
            rows = toolbox.matching(c)
            what = " ".join(x for x in (c.type, c.method and f"checked-{c.method}", c.fuel_class and f"{c.fuel_class}-fuel", "investigations",
                                        c.reuses_flight_data and "that use flight data") if x)
            out["list"] = {"title": f"{len(rows)} {what}, counted by code", "note": "Only investigations whose method label was checked are counted." if c.method else None,
                           "rows": [{"psi": i["id"], "name": i["name"], "title": i["title"], "type": i["project_type"], "method": i["method"]["flag"],
                                     "method_status": i["method"]["status"]} for i in rows]}
    return out


def build_report(*, question: str, frame: Frame, calls: list[dict], evidence: list[Item], verification, library: Library,
                 mode: str, model: str | None, notes: list[str], run_id: str, direct: list[dict] | None = None) -> dict:
    """mode: "si" (an SI-written answer, checked), "computed" (written by code straight from the data, no SI),
    "no_answer" (SI wrote nothing that survived), "sources_only" (SI unavailable)."""
    catalog = library.catalog
    order: list[int] = []                                    # evidence numbers in the order the kept answer first cites them
    kept = verification.kept if verification else (direct or [])     # `direct`: sentences code wrote from the data, no SI
    for s in kept:
        for c in s["cites"]:
            if c not in order:
                order.append(c)
    display = {e: n for n, e in enumerate(order, 1)}
    answer = [{"text": s["text"], "cites": [display[c] for c in s["cites"]]} for s in kept]
    if order:
        sources = [source_entry(display[e], evidence[e - 1], library) for e in order]
    else:   # nothing to cite: show the best evidence found, marked as not cited
        sources = [dict(source_entry(n, i, library), shown_not_cited=True) for n, i in enumerate(evidence[:4], 1)]
    for src in sources:                                      # per source: which sentences cite it, and what Nimbus confirmed in it
        by = [n for n, a in enumerate(answer, 1) if src["n"] in a["cites"]]
        src["cited_by"] = by
        item = evidence[order[src["n"] - 1] - 1] if order else None
        src["checks"] = source_checks([answer[n - 1]["text"] for n in by], item, library) if item and by else []
    removed = [{"text": r.text, "reason": r.reason, "rules": r.rules} for r in (verification.removed if verification else [])]
    covered = not_covered(frame, evidence, catalog)
    if mode == "no_answer":
        answer = [{"text": NO_ANSWER, "cites": [], "note": True}]
    stats = {"evidence": len(evidence), "sentences_checked": verification.checked if verification else 0,
             "kept": len(answer) if mode in ("si", "computed") else 0, "removed": len(removed),
             "not_checked": verification.truncated if verification else 0}
    return {"run_id": run_id, "question": question, "mode": mode, "model": model, "chips": frame.chips({i["id"]: i["name"] for i in catalog.ordered()}),
            "answer": answer, "sources": sources, "removed": removed, "not_covered": covered, "followups": followups(frame, catalog),
            "tools": calls, "notes": notes, "stats": stats}
