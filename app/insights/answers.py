"""Answers that code writes from the PSI data, with no SI: a safety stance, coverage of a stated condition, and a habitat reference count.

Each is returned as a computed evidence Item (so it is cited and shown in the sources like any other fact) plus, where the
question is only that, the sentence to show directly. A habitat is the NASA Space Apps challenge's reference atmosphere, not PSI
data, and the answer says so every time it is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.analysis.habitats import in_box
from app.analysis import compare as compare_mod
from app.analysis.rank import NEAR_O2, NEAR_PSI
from app.analysis.sweeper import _value
from app.catalog import Catalog
from app.insights.frame import Frame
from app.insights.library import Item
from app.insights.tools import computed

HABITAT_WORDS = re.compile(r"\b(habitats?|moon|lunar|rover|spacesuit|space suit|eva|iss|space station|cabin|spacecraft)\b", re.I)
HABITAT_NOTE = ("Habitat atmospheres are the NASA Space Apps challenge's reference values, not PSI data; "
                "the band around each value is the team's assumption.")
SAFETY_TEXT = ("SI Insights is a research tool. It cannot tell whether a fire is happening and it gives no emergency instructions. "
               "If you suspect a fire, follow your spacecraft's or facility's fire procedures and alarms. "
               "What it can do is show what NASA's microgravity combustion experiments in PSI found about flames, smoke detection and suppression.")


@dataclass
class Special:
    items: list[Item] = field(default_factory=list)      # computed evidence to put first
    direct: list[dict] | None = None                      # sentences to show as the whole answer (no SI)
    only: bool = False                                    # the items replace everything else found
    habitat: dict | None = None                           # the reference habitat used, for the answer's footnote


def _tests(catalog: Catalog) -> list[tuple[dict, float, float]]:
    out = []
    for t in catalog.tests:
        if t.get("o2_role") != "ambient":
            continue                                       # a burner-stream oxygen is not the chamber atmosphere
        o2, p = _value(t, "o2_fraction"), _value(t, "pressure_psi")
        if o2 is not None and p is not None:
            out.append((t, o2, p))
    return out


def _names(catalog: Catalog, tests: list[dict], limit: int = 3) -> str:
    ids = sorted({t["investigation"] for t in tests}, key=lambda s: int(s.split("-")[1]))
    names = [catalog.get(i)["name"] for i in ids]
    return ", ".join(names[:limit]) + (f" and {len(names) - limit} more" if len(names) > limit else "")


def _span(lo: float, hi: float, unit: str) -> str:
    fmt = (lambda v: f"{v:.0%}") if unit == "%" else (lambda v: f"{v:.1f}")
    return fmt(lo) if fmt(lo) == fmt(hi) else f"{fmt(lo)} to {fmt(hi)}" + ("" if unit == "%" else unit)


def coverage(frame: Frame, catalog: Catalog) -> Item | None:
    """Which mapped tests lie at the oxygen and pressure the question states, or the nearest tested values."""
    if frame.psi_ids or not (frame.o2 or frame.pressure):
        return None
    pool = _tests(catalog)
    lo_o, hi_o = ((frame.o2 or {}).get("min"), (frame.o2 or {}).get("max"))
    lo_p, hi_p = ((frame.pressure or {}).get("min"), (frame.pressure or {}).get("max"))
    hits = [(t, o, p) for t, o, p in pool if (lo_o is None or o >= lo_o) and (hi_o is None or o <= hi_o) and (lo_p is None or p >= lo_p) and (hi_p is None or p <= hi_p)]
    want = " and ".join(x["text"] for x in (frame.o2, frame.pressure) if x)
    text = (f"Searched the {len(pool)} PSI tests whose oxygen and pressure are mapped, from {len({t['investigation'] for t, _, _ in pool})} investigations "
            f"(inverse-flame tests are left out: their oxygen is the burner stream, not the chamber). {len(hits)} match {want}.")
    if hits:
        os_, ps = [o for _, o, _ in hits], [p for _, _, p in hits]
        text += (f" They come from {_names(catalog, [t for t, _, _ in hits])}; oxygen runs {_span(min(os_), max(os_), '%')} and pressure {_span(min(ps), max(ps), ' psi')}.")
    elif frame.o2:
        target = ((lo_o if lo_o is not None else hi_o) if hi_o is None or lo_o is None else (lo_o + hi_o) / 2)
        below = [(t, o) for t, o, _ in pool if o < target]
        above = [(t, o) for t, o, _ in pool if o >= target]
        if below:
            b = max(o for _, o in below)
            text += f" The nearest tested oxygen below that is {b:.1%} ({_names(catalog, [t for t, o in below if o == b])})."
        if above:
            a = min(o for _, o in above)
            text += f" The nearest above is {a:.1%} ({_names(catalog, [t for t, o in above if o == a])})."
    text += " Tests in tables whose columns are not mapped cannot be searched this way, so a missing match is not proof that nothing was tested."
    return computed("coverage:" + re.sub(r"\W+", "_", want), text)


def habitat_reference(frame: Frame, catalog: Catalog, habitat: dict | None) -> Item | None:
    if not habitat or not HABITAT_WORDS.search(frame.question):
        return None
    pool = _tests(catalog)
    box = [(t, o, p) for t, o, p in pool if in_box(habitat, o, p)]
    h_o, h_p = habitat["o2"], habitat["pressure_psi"]
    near = [(t, o, p) for t, o, p in pool if (t, o, p) not in box and h_o[0] - NEAR_O2 <= o <= h_o[1] + NEAR_O2 and h_p[0] - NEAR_PSI <= p <= h_p[1] + NEAR_PSI]
    text = (f"Reference habitat: {habitat['label']}, {habitat['summary']} (NASA Space Apps challenge reference, not PSI data; band: oxygen {h_o[0]:.0%} to {h_o[1]:.0%}, "
            f"pressure {h_p[0]:.1f} to {h_p[1]:.1f} psi). Of the {len(pool)} mapped PSI tests, {len(box)} lie inside that band")
    if box:
        text += f" ({_names(catalog, [t for t, _, _ in box])})"
    text += f" and {len(near)} more lie within {NEAR_O2:g} oxygen and {NEAR_PSI:g} psi of it."
    return computed("habitat:" + habitat["key"], text)


def build(frame: Frame, catalog: Catalog, habitat: dict | None) -> Special:
    if "safety" in frame.intents:
        item = computed("safety", SAFETY_TEXT)
        return Special([item], [{"text": SAFETY_TEXT, "cites": [1]}], only=True)
    items: list[Item] = []
    cov, hab = coverage(frame, catalog), habitat_reference(frame, catalog, habitat)
    items += [i for i in (cov, hab) if i]
    direct = None
    if cov or (hab and not frame.topics and not frame.psi_ids and not (set(frame.intents) - {"tests", "list"})):
        direct = [{"text": i.text, "cites": [n]} for n, i in enumerate(items, 1)][:2]
    return Special(items, direct, habitat={"key": habitat["key"], "label": habitat["label"], "note": HABITAT_NOTE} if hab and habitat else None)


def facts(frame: Frame, catalog: Catalog) -> dict | None:
    """What PSI's own record and tables say about the investigations a question names, as a table written by code (no SI)."""
    ids = [i for i in frame.psi_ids[:3] if catalog.get(i)]
    if not ids:
        return None
    profiles = {i: compare_mod.profile(catalog.get(i)) for i in ids}
    order = list(dict.fromkeys(a for p in profiles.values() for a in p))
    rows = []
    for attr in order:
        cells = {i: [v for v in profiles[i].get(attr, []) if v] for i in ids}
        if any(cells.values()):
            rows.append({"attribute": attr, "cells": cells, "all_same": len(ids) > 1 and len({tuple(v) for v in cells.values()}) == 1})
    rows.append({"attribute": "DOI", "cells": {i: [catalog.get(i)["doi"]] if catalog.get(i).get("doi") else [] for i in ids}, "all_same": False})
    return {"title": "Facts from PSI's records and test tables (computed by code)",
            "columns": [{"psi": i, "name": catalog.get(i)["name"]} for i in ids], "rows": rows}


def links(frame: Frame, special: Special) -> list[dict]:
    """Where in the dashboard to look next, chosen from what the question was about. The page builds the addresses."""
    out = []
    if len(frame.psi_ids) >= 2:
        out.append({"kind": "compare", "label": "Compare these investigations", "ids": frame.psi_ids[:4]})
    if len(frame.psi_ids) == 1:
        out.append({"kind": "detail", "label": "Open the investigation", "psi": frame.psi_ids[0]})
    if frame.o2 or frame.pressure or special.habitat:
        out.append({"kind": "sweeper", "label": "See these conditions in the Flame Sweeper"})
    return out[:3]


__all__ = ["Special", "build", "facts", "links", "HABITAT_NOTE"]
