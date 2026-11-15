"""Mission Fit: a transparent, deterministic score for each investigation. No SI.

Four components, each 0..1 and each shown with the data behind it. The browser
applies the weights, so a user can change them and see the ranking move.

A component that can't be computed is `None` ("unknown"), never zero: a missing
test table must not read as "NASA didn't test this".
"""

from __future__ import annotations

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
    return {"score": score, "why": why + " Solids (fabrics, plastics) are the main habitat fire load."}


def pillar(inv: dict, wanted: str | None) -> dict:
    """How well the record shows the research informs a fire-safety pillar: a quoted sentence and measured results, not keyword counts."""
    pillars = inv["pillars"]
    name = wanted or max(pillar_mod.PILLARS, key=lambda p: pillars[p]["score"] or 0.0)
    record = pillars[name]
    return {"score": record["score"], "pillar": name, "status": record["status"], "points": record["points"],
            "why": f"{name.capitalize()}: {pillar_mod.describe(record)}"}


ROWS_FULL, PUBLICATIONS_FULL, DOCUMENTS_FULL = 100, 10, 5     # amounts that count as a full score for each kind of data


def data_richness(inv: dict) -> dict:
    """How much PSI data the dashboard holds for an investigation: test-table rows, publications, documents read.

    Rows count whether or not their columns are mapped yet: a downloaded table is data we hold.
    """
    if not inv["record_complete"]:
        return {"score": None, "why": "Unknown: PSI's full record (test tables, DOI, files) wasn't available "
                                      "when the snapshot was taken."}
    rows, pubs = inv["table_rows"], len(inv["publications"])
    docs = sum(1 for d in inv["documents"] if d["status"] == "read")
    score = (0.4 * min(1.0, rows / ROWS_FULL) + 0.3 * min(1.0, pubs / PUBLICATIONS_FULL) + 0.3 * min(1.0, docs / DOCUMENTS_FULL))
    return {"score": score, "rows": rows, "publications": pubs, "documents": docs,
            "why": f"{rows} test-table rows, {pubs} publications and {docs} documents read "
                   f"(full marks at {ROWS_FULL} rows, {PUBLICATIONS_FULL} publications, {DOCUMENTS_FULL} documents)."}


def score(inv: dict, tests: list[dict], habitat: dict, wanted_pillar: str | None) -> dict:
    components = {"proximity": proximity(tests, habitat, inv.get("tables_status")), "fuel": fuel(inv["attributes"]),
                  "pillar": pillar(inv, wanted_pillar), "data": data_richness(inv)}
    return {"components": components,
            "factor": 1.0 if inv["is_combustion"] else OFF_TOPIC_FACTOR,
            "factor_reason": None if inv["is_combustion"] else
            f"Not a combustion investigation ({inv['research_area']}). It is in the PSI search results "
            f"because it {inv['match_reason']}."}


def total(result: dict, weights: dict = DEFAULT_WEIGHTS) -> float:
    """0..100. Unknown components count as zero and are reported as unknown."""
    weight_sum = sum(weights.values()) or 1
    raw = sum(weights[k] * (c["score"] or 0.0) for k, c in result["components"].items()) / weight_sum
    return round(100 * raw * result["factor"], 1)
