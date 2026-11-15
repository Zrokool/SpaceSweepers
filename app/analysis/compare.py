"""Side-by-side comparison of investigations, and the relationship graph. No SI."""

from __future__ import annotations

from app.catalog import Catalog


def _labels(items: list[dict], key: str = "label") -> list[str]:
    return sorted({i[key] for i in items})


def _range_text(r: list[float] | None, unit: str) -> str | None:
    return None if not r else (f"{r[0]:g} {unit}" if r[0] == r[1] else f"{r[0]:g}–{r[1]:g} {unit}")


def profile(inv: dict) -> dict[str, list[str]]:
    """The comparable attributes of one investigation, each as a list of short values."""
    a, s = inv["attributes"], inv["stats"]
    method = inv["method"]
    rows = {
        "Type": [inv["project_type"]],
        "Method": method.get("labels") or ["Not classified"],
        "Uses flight data from": inv["uses_data_from"],
        "Platform": [inv["platform"]] if inv["platform"] else [],
        "Hardware": _labels(a["hardware"]),
        "Fuel classes": a["fuel_classes"],
        "Fuels named": sorted({f["term"].lower() for f in a["fuels"]}),
        "Sensors": _labels(a["sensors"]),
        "Fire-safety pillars informed": [p for p, v in inv["pillars"].items() if v["status"] in ("evidence", "data only")],
    }
    if s:
        for role, info in s["o2_by_role"].items():
            rows[f"Oxygen ({role.replace('_', ' ')})"] = [_range_text(info["range"], "mole fraction")] if info["range"] else []
        rows["Pressure"] = [t] if (t := _range_text([round(x, 1) for x in s["pressure_psi"]] if s["pressure_psi"] else None, "psi")) else []
        rows["Varied between tests"] = [v["variable"] for v in s["varied"]]
        rows["Tests"] = [str(s["tests"])]
    return rows


def compare(catalog: Catalog, ids: list[str]) -> dict:
    invs = [catalog.investigations[i] for i in ids]
    profiles = {inv["id"]: profile(inv) for inv in invs}
    attributes = []
    for name in dict.fromkeys(k for p in profiles.values() for k in p):
        cells = {i: profiles[i].get(name) for i in ids}
        known = {i: set(v) for i, v in cells.items() if v}
        shared = sorted(set.intersection(*known.values())) if len(known) == len(ids) else []
        attributes.append({"attribute": name, "cells": {i: v or [] for i, v in cells.items()},
                           "shared": shared, "all_same": bool(known) and len(known) == len(ids)
                           and all(v == next(iter(known.values())) for v in known.values())})
    links = [e for e in catalog.lineage if e["from"] in ids and e["to"] in ids]
    return {"investigations": [{"id": i["id"], "name": i["name"], "title": i["title"]} for i in invs],
            "attributes": attributes, "links": links}


def graph(catalog: Catalog) -> dict:
    """Investigations and shared hardware as nodes; lineage and hardware use as edges."""
    nodes = [{"id": i["id"], "kind": "investigation", "label": i["name"], "type": i["project_type"],
              "is_combustion": i["is_combustion"], "method": i["method"]["flag"]} for i in catalog.ordered()]
    edges = [{"from": e["from"], "to": e["to"], "relation": e["relation"]} for e in catalog.lineage if e["in_scope"]]
    hardware: dict[str, list[str]] = {}
    for inv in catalog.ordered():
        if inv["project_type"] != "Microgravity":
            continue  # a ground study naming a rig in its text didn't run on it
        for h in inv["attributes"]["hardware"]:
            hardware.setdefault(h["label"], []).append(inv["id"])
    for label, users in hardware.items():
        if len(users) < 2:
            continue
        nodes.append({"id": f"hw:{label}", "kind": "hardware", "label": label})
        edges += [{"from": u, "to": f"hw:{label}", "relation": "ran on"} for u in users]
    return {"nodes": nodes, "edges": edges}
