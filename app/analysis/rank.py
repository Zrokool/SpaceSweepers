"""Mission Fit: a transparent, deterministic score for each investigation. No SI.

Four components, each 0..1 and each shown with the data behind it. The browser
applies the weights, so a user can change them and see the ranking move.

A component that can't be computed is `None` ("unknown"), never zero: a missing
test table must not read as "NASA didn't test this".
"""

from __future__ import annotations

import random
from collections import Counter

from app.analysis import pillars as pillar_mod
from app.analysis.habitats import in_box

DEFAULT_WEIGHTS = {"proximity": 40, "fuel": 25, "pillar": 20, "data": 15}
FUEL_SCORE = {"solid": 1.0, "liquid": 0.6, "gas": 0.4}
SOLID_EMULATION_SCORE = 0.8
PROXIMITY_FULL = 20      # tests inside the habitat box that count as full proximity
NEAR_O2, NEAR_PSI = 0.05, 2.0
OFF_TOPIC_FACTOR = 0.25  # applied to investigations outside Combustion Science
USABLE = ("ok", "approx", "range")


def _value(test: dict, variable: str) -> float | None:
    v = test["values"].get(variable)
    return v["value"] if v and v["flag"] in USABLE else None


def proximity(tests: list[dict], habitat: dict, tables_status: str | None = None) -> dict:
    """How many tests sit in or near the habitat's atmosphere.

    Only tests whose oxygen value describes the surrounding atmosphere count. A
    burner-stream oxygen fraction (CFI-G inverse flames) says nothing about room air.
    """
    if not tests:
        reason = (tables_status or "no test table is available").rstrip(".")
        return {"score": None, "why": f"No tests are mapped for this investigation ({reason}), so its condition match is unknown, not zero."}
    ambient = [t for t in tests if t["o2_role"] == "ambient"]
    other_roles = sorted({t["o2_role"] for t in tests if t["o2_role"] and t["o2_role"] != "ambient"})
    if not ambient:
        return {"score": 0.0, "inside": 0, "near": 0, "tests": len(tests),
                "why": f"{len(tests)} tests, but their oxygen values are {' / '.join(other_roles) or 'unlabelled'} "
                       "fractions, not the oxygen of the surrounding atmosphere. None can be placed in the habitat box."}
    # Only a test that records both oxygen and pressure can be placed in the box. A table with oxygen but no pressure
    # column (BASS-II) says nothing about the box, so its condition match is unknown, never zero.
    placed = [t for t in ambient if _value(t, "o2_fraction") is not None and _value(t, "pressure_psi") is not None]
    if not placed:
        return {"score": None, "inside": 0, "near": 0, "tests": len(ambient),
                "why": f"{len(ambient)} tests record the room-air oxygen but not the pressure (or no usable value), so none can be placed in the habitat box."}
    unplaced = len(ambient) - len(placed)
    inside = near = 0
    (o2_lo, o2_hi), (p_lo, p_hi) = habitat["o2"], habitat["pressure_psi"]
    for t in placed:
        o2, p = _value(t, "o2_fraction"), _value(t, "pressure_psi")
        if in_box(habitat, o2, p):
            inside += 1
        elif o2 is not None and p is not None and o2_lo - NEAR_O2 <= o2 <= o2_hi + NEAR_O2 \
                and p_lo - NEAR_PSI <= p <= p_hi + NEAR_PSI:
            near += 1
    return {"score": min(1.0, (inside + 0.5 * near) / PROXIMITY_FULL), "inside": inside, "near": near,
            "tests": len(placed),
            "why": f"{inside} of {len(placed)} tests inside the habitat box, {near} more nearby."
                   + (f" {unplaced} more record no usable pressure and can't be placed." if unplaced else "")}


def fuel(attributes: dict) -> dict:
    classes = attributes["fuel_classes"]
    score = max([FUEL_SCORE[c] for c in classes], default=0.0)
    why = f"Fuel terms found: {', '.join(classes)}." if classes else "No fuel term found in the record text."
    if attributes["solid_emulation"] and score < SOLID_EMULATION_SCORE:
        score = SOLID_EMULATION_SCORE
        why += " Emulates burning solids with a gas burner."
    if not classes and not attributes["solid_emulation"]:
        # No fuel word is a gap in what we know, not a finding that the fuel is harmless.
        return {"score": None, "why": why + " The fuel is unknown, not zero."}
    return {"score": score, "why": why + " Solids (fabrics, plastics) are the main habitat fire load."}


def pillar(inv: dict, wanted: str | None) -> dict:
    """How well the record shows the research informs a fire-safety pillar: a quoted sentence and measured results, not keyword counts."""
    pillars = inv["pillars"]
    name = wanted or max(pillar_mod.PILLARS, key=lambda p: pillars[p]["score"] or 0.0)
    record = pillars[name]
    return {"score": record["score"], "pillar": name, "status": record["status"], "points": record["points"],
            "why": f"{name.capitalize()}: {pillar_mod.describe(record)}"}


ROWS_FULL, PUBLICATIONS_FULL, DOCUMENTS_FULL = 100, 10, 5     # amounts that count as a full score for each kind of data
FIGURES_FULL, FIGURE_CREDIT = 5, 0.2     # stored Analyzed Data figures add up to this much extra, so investigations without figures keep their score


def data_richness(inv: dict) -> dict:
    """How much PSI data the dashboard holds for an investigation: test-table rows, publications, documents read.

    Rows count whether or not their columns are mapped yet: a downloaded table is data we hold.
    """
    if not inv["record_complete"]:
        return {"score": None, "why": "Unknown: PSI's full record (test tables, DOI, files) wasn't available "
                                      "when the snapshot was taken."}
    rows, pubs = inv["table_rows"], len(inv["publications"])
    docs = sum(1 for d in inv["documents"] if d["status"] == "read")
    figures = len(inv.get("analyzed") or [])
    base = 0.4 * min(1.0, rows / ROWS_FULL) + 0.3 * min(1.0, pubs / PUBLICATIONS_FULL) + 0.3 * min(1.0, docs / DOCUMENTS_FULL)
    score = min(1.0, base + FIGURE_CREDIT * min(1.0, figures / FIGURES_FULL))
    return {"score": score, "rows": rows, "publications": pubs, "documents": docs, "figures": figures,
            "why": f"{rows} test-table rows, {pubs} publications and {docs} documents read "
                   f"(full marks at {ROWS_FULL} rows, {PUBLICATIONS_FULL} publications, {DOCUMENTS_FULL} documents)."
                   + (f" {figures} stored PSI Analyzed Data figure{'s' if figures != 1 else ''} add up to {int(FIGURE_CREDIT * 100)}% extra "
                      f"(full at {FIGURES_FULL}); figures are data we hold, never condition evidence." if figures else "")}


def score(inv: dict, tests: list[dict], habitat: dict, wanted_pillar: str | None) -> dict:
    components = {"proximity": proximity(tests, habitat, inv.get("tables_status")), "fuel": fuel(inv["attributes"]),
                  "pillar": pillar(inv, wanted_pillar), "data": data_richness(inv)}
    return {"components": components,
            "unknown": [k for k, c in components.items() if c["score"] is None],
            "factor": 1.0 if inv["is_combustion"] else OFF_TOPIC_FACTOR,
            "factor_reason": None if inv["is_combustion"] else
            f"Not a combustion investigation ({inv['research_area']}). It is in the PSI search results "
            f"because it {inv['match_reason']}."}


def _blend(result: dict, weights: dict, fill: float) -> float:
    """0..100 over the parts named in `weights`; a part that can't be computed counts as `fill`."""
    weight_sum = sum(weights.values()) or 1
    raw = sum(w * (result["components"][k]["score"] if result["components"][k]["score"] is not None else fill)
              for k, w in weights.items()) / weight_sum
    return 100 * raw * result["factor"]


def total(result: dict, weights: dict = DEFAULT_WEIGHTS) -> float:
    """0..100, the proven fit: what the data shows. A part that can't be computed counts as zero and is reported as unknown."""
    return round(_blend(result, weights, 0.0), 1)


def ceiling(result: dict, weights: dict = DEFAULT_WEIGHTS) -> float:
    """0..100 if every unknown part turned out perfect. Never used for ranking; it shows how much is still open."""
    return round(_blend(result, weights, 1.0), 1)


def stability(results: dict[str, dict], parts: tuple[str, ...] = tuple(DEFAULT_WEIGHTS), runs: int = 400, seed: int = 7, top: int = 5) -> dict[str, float]:
    """Share of random weightings (each weight between 5 and 50) in which an investigation lands in the top `top`.

    Shows how much of the ranking depends on our weights. Deterministic: the same seed gives the same answer.
    """
    rng, counts = random.Random(seed), Counter()
    for _ in range(runs):
        w = {k: rng.uniform(5, 50) for k in parts}
        ranked = sorted(results, key=lambda i: (-_blend(results[i], w, 0.0), i))
        counts.update(ranked[:top])
    return {i: round(n / runs, 2) for i, n in counts.most_common() if n / runs >= 0.05}


def method() -> dict:
    """The scoring rules as constants, so the page that explains them cannot drift from the code."""
    return {"weights": DEFAULT_WEIGHTS, "fuel_scores": FUEL_SCORE, "solid_emulation_score": SOLID_EMULATION_SCORE,
            "proximity_full": PROXIMITY_FULL, "near": {"o2": NEAR_O2, "pressure_psi": NEAR_PSI},
            "off_topic_factor": OFF_TOPIC_FACTOR,
            "data_full": {"rows": ROWS_FULL, "publications": PUBLICATIONS_FULL, "documents": DOCUMENTS_FULL, "figures": FIGURES_FULL},
            "figure_credit": FIGURE_CREDIT}
