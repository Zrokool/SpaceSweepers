"""The tested envelope: every harmonised test as a point in (oxygen, pressure) space. No SI."""

from __future__ import annotations

from collections import Counter

from app.analysis.habitats import in_box
from app.catalog import Catalog

USABLE = ("ok", "approx", "range")


def _value(test: dict, variable: str):
    v = test["values"].get(variable)
    return v["value"] if v and v["flag"] in USABLE else None


def envelope(catalog: Catalog, habitat: dict, measured_only: bool = False) -> dict:
    points, skipped = [], Counter()
    for t in catalog.tests:
        inv = catalog.investigations[t["investigation"]]
        if measured_only and inv["method"]["flag"] == "simulation":
            skipped["modelled, not measured"] += 1
            continue
        o2, pressure = _value(t, "o2_fraction"), _value(t, "pressure_psi")
        if o2 is None or pressure is None:
            skipped["no usable oxygen or pressure value"] += 1
            continue
        ambient = t["o2_role"] == "ambient"
        points.append({"investigation": t["investigation"], "name": inv["name"], "test_id": t["test_id"],
                       "o2": o2, "pressure_psi": round(pressure, 2), "o2_role": t["o2_role"],
                       "fuel_class": t["fuel_class"], "fuel": _value(t, "fuel"), "outcome": _value(t, "outcome"),
                       "file": t["file"], "row": t["row"],
                       # Only ambient-oxygen tests can sit in a habitat's atmosphere.
                       "in_box": ambient and in_box(habitat, o2, pressure)})
    inside = [p for p in points if p["in_box"]]
    not_ambient = [p for p in points if p["o2_role"] != "ambient" and in_box(habitat, p["o2"], p["pressure_psi"])]
    without_tables = [i["id"] for i in catalog.ordered() if i["is_combustion"] and not i["stats"]]
    return {
        "points": points, "skipped": dict(skipped),
        "gaps": {
            "in_box": len(inside),
            "in_box_by_fuel_class": dict(Counter(p["fuel_class"] or "unknown" for p in inside)),
            "look_alike": len(not_ambient),
            "look_alike_note": (f"{len(not_ambient)} tests have numbers inside the box but their oxygen value is a "
                                "burner-stream fraction, not room air. They are not counted.") if not_ambient else None,
            "investigations_without_tables": without_tables,
            "caveat": (f"{len(without_tables)} of the combustion investigations have no test data on this chart yet "
                       "(their tables aren't mapped yet, or PSI lists none), so a count of zero here means "
                       "'not in the data we hold', not 'never tested'.")
            if without_tables else None,
        },
    }
