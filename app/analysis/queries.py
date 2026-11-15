"""Scenario analyses over the harmonised PSI tests: the answers a researcher or engineer needs, computed by code. No SI.

Every function returns numbers and test rows (file and row), never prose that was not computed. A threshold is the lowest value at
which an outcome was actually seen, with what happened below it. A comparison is observed counts only: PSI's tests did not vary
one gas at a time, and the result says so.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from app.analysis.rank import NEAR_O2, NEAR_PSI
from app.analysis.sweeper import ATM_PSI, _value, wilson
from app.catalog import Catalog

# Names a person uses for what the tables write in many ways. Only fuels and materials that are in the mapped tests.
FUEL_ALIASES = {
    "methanol": ["methanol"], "heptane": ["heptane"], "n-dodecane": ["c12h26", "dodecane"], "farnesane": ["farnesane"],
    "ethane": ["ethane"], "propane": ["propane", "c3h8"], "butane": ["butane"], "ethylene": ["c2h4", "ethylene"],
    "PMMA": ["pmma"], "SIBAL (cotton-fiberglass)": ["sibal"], "Nomex": ["nomex"], "wax": ["wax", "candle", "paraffin", "parrafin"], "Ultem": ["ultem"],
}
FUEL_WORDS = {  # words in a question -> a key of FUEL_ALIASES
    "methanol": "methanol", "heptane": "heptane", "dodecane": "n-dodecane", "c12h26": "n-dodecane", "farnesane": "farnesane", "ethane": "ethane",
    "propane": "propane", "butane": "butane", "ethylene": "ethylene", "pmma": "PMMA", "acrylic": "PMMA", "plexiglas": "PMMA",
    "sibal": "SIBAL (cotton-fiberglass)", "nomex": "Nomex", "wax": "wax", "candle": "wax", "paraffin": "wax", "ultem": "Ultem",
}
DILUENTS = ("helium", "carbon dioxide", "nitrogen only")
OUTCOME_TEXT = {"extinguished": "went out by itself", "completed": "burned until the test ended", "disrupted": "was disturbed while burning",
                "ignited": "a hot flame lit", "no_ignition": "no hot flame lit", "flash": "only a brief flash", "reignited": "the flame reignited",
                "no_reignition": "the flame did not reignite", "burned": "the notes say it burned"}
# What "it burned", "it went out", "it lit" and "it reignited" mean in each kind of test (the Sweeper's own definitions).
TARGETS = {
    "burn": {"end_state": {"completed", "disrupted"}, "ignition": {"ignited"}, "burn": {"burned"}},
    "extinguish": {"end_state": {"extinguished"}},
    "ignite": {"ignition": {"ignited"}},
    "reignite": {"reignition": {"reignited"}},
}
TARGET_TEXT = {"burn": "burned", "extinguish": "went out by itself", "ignite": "lit", "reignite": "reignited"}


def fuel_key(value) -> str | None:
    text = str(value or "").lower()
    return next((key for key, names in FUEL_ALIASES.items() if any(n in text for n in names)), None)


def diluent_of(test: dict) -> str:
    he, co2 = _value(test, "he_fraction") or 0.0, _value(test, "co2_fraction") or 0.0
    return "helium" if he > 0 else "carbon dioxide" if co2 > 0 else "nitrogen only"


def all_rows(catalog: Catalog) -> list[dict]:
    """Every test whose oxygen is the chamber atmosphere and whose oxygen and pressure are known, as plain rows."""
    cached = getattr(catalog, "_scenario_rows", None)
    if cached is not None:
        return cached
    names = {i["id"]: i["name"] for i in catalog.ordered()}
    rows = []
    for t in catalog.tests:
        if t.get("o2_role") != "ambient":
            continue
        o2, p = _value(t, "o2_fraction"), _value(t, "pressure_psi")
        if o2 is None or p is None:
            continue
        doc = (t["values"].get("outcome") or {}).get("flag") == "document_text"
        outcome = (t["values"]["outcome"]["value"] if doc else _value(t, "outcome"))
        fuel = _value(t, "fuel")
        rows.append({"psi": t["investigation"], "name": names.get(t["investigation"], t["investigation"]), "file": t["file"], "row": t["row"],
                     "test_id": t["test_id"], "o2": o2, "p_psi": p, "p_atm": p / ATM_PSI, "fuel": str(fuel) if fuel else None, "fuel_key": fuel_key(fuel),
                     "diluent": diluent_of(t), "kind": t.get("outcome_kind"), "outcome": outcome, "document": doc,
                     "droplet_mm": _value(t, "droplet_diameter_mm")})
    catalog._scenario_rows = rows
    return rows


def left_out(catalog: Catalog) -> dict:
    """Tests with a recorded outcome that these analyses cannot use, and why (never dropped silently)."""
    used = {(r["file"], r["row"]) for r in all_rows(catalog)}
    burner = missing = 0
    for t in catalog.tests:
        has_outcome = bool((t["values"].get("outcome") or {}).get("value")) and ((t["values"]["outcome"]["flag"] == "document_text") or _value(t, "outcome"))
        if not has_outcome or (t["file"], t["row"]) in used:
            continue
        if t.get("o2_role") != "ambient":
            burner += 1
        else:
            missing += 1
    return {"burner_stream": burner, "missing_condition": missing}


@dataclass
class Scope:
    fuel: str | None = None                 # a key of FUEL_ALIASES
    diluent: str | None = None              # helium | carbon dioxide | nitrogen only
    o2: tuple[float | None, float | None] | None = None
    p_psi: tuple[float | None, float | None] | None = None
    psi_ids: list[str] = field(default_factory=list)
    kind: str | None = None                 # an outcome kind: end_state | ignition | reignition | burn
    with_outcome: bool = False

    def text(self) -> str:
        bits = []
        if self.fuel:
            bits.append(self.fuel)
        if self.diluent:
            bits.append(f"{self.diluent} in the chamber gas" if self.diluent != "nitrogen only" else "nitrogen as the only other gas")
        for label, rng, unit, scale in (("oxygen", self.o2, "%", 100), ("pressure", self.p_psi, " psi", 1)):
            if rng and (rng[0] is not None or rng[1] is not None):
                lo, hi = rng
                f = (lambda v: f"{v * scale:g}") if label == "oxygen" else (lambda v: f"{v:.1f}")
                bits.append(f"{label} {f(lo)} to {f(hi)}{unit}" if lo is not None and hi is not None else
                            f"{label} at least {f(lo)}{unit}" if lo is not None else f"{label} at most {f(hi)}{unit}")
        return ", ".join(bits) or "all mapped tests"


def select(catalog: Catalog, scope: Scope) -> list[dict]:
    out = []
    for r in all_rows(catalog):
        if scope.psi_ids and r["psi"] not in scope.psi_ids:
            continue
        if scope.fuel and r["fuel_key"] != scope.fuel:
            continue
        if scope.diluent and r["diluent"] != scope.diluent:
            continue
        if scope.kind and r["kind"] != scope.kind:
            continue
        if scope.with_outcome and not r["outcome"]:
            continue
        if scope.o2 and ((scope.o2[0] is not None and r["o2"] < scope.o2[0]) or (scope.o2[1] is not None and r["o2"] > scope.o2[1])):
            continue
        if scope.p_psi and ((scope.p_psi[0] is not None and r["p_psi"] < scope.p_psi[0]) or (scope.p_psi[1] is not None and r["p_psi"] > scope.p_psi[1])):
            continue
        out.append(r)
    return out


def positive(row: dict, target: str) -> bool | None:
    """True when the row's outcome is the target, False when it is a different outcome of the same kind, None when it has no outcome."""
    if not row["outcome"]:
        return None
    kinds = TARGETS[target]
    if row["kind"] not in kinds:
        return None
    return row["outcome"] in kinds[row["kind"]]


def short_file(name: str) -> str:
    """A table file name without the PSI id, kind and extension: 'PSI-69_Experimental table_FLEX.csv' -> 'FLEX'."""
    return re.sub(r"^PSI-\d+_(?:Experimental table_|Workbook table_)?", "", name).removesuffix(".csv")


def table(rows: list[dict], limit: int = 12) -> dict:
    cols = ["Investigation", "Test", "Oxygen", "Pressure (psi)", "Gas / fuel", "What happened", "Source"]
    body = [[r["name"], r["test_id"], f"{r['o2']:.3f}", f"{r['p_psi']:.1f}", f"{r['fuel'] or '–'}" + (f" + {r['diluent']}" if r["diluent"] != "nitrogen only" else ""),
             OUTCOME_TEXT.get(r["outcome"], r["outcome"] or "no outcome recorded"), f"{short_file(r['file'])}, row {r['row']}"]
            for r in rows[:limit]]
    return {"columns": cols, "rows": body, "shown": len(body), "total": len(rows), "psi": [r["psi"] for r in rows[:limit]]}


# ------------------------------------------------------------------ the analyses
def nearest(catalog: Catalog, o2: float, p_psi: float, scope: Scope, k: int = 12) -> dict:
    """The tested conditions closest to a stated atmosphere, with what happened there."""
    pool = select(catalog, scope)
    dist = lambda r: math.hypot((r["o2"] - o2) / NEAR_O2, (r["p_psi"] - p_psi) / NEAR_PSI)   # noqa: E731
    ranked = sorted(pool, key=dist)
    near = [r for r in ranked if abs(r["o2"] - o2) <= NEAR_O2 and abs(r["p_psi"] - p_psi) <= NEAR_PSI]
    shown = near[:k] if near else ranked[:k]
    by = Counter((r["name"], r["fuel"] or "–", OUTCOME_TEXT.get(r["outcome"], "no outcome recorded")) for r in near)
    return {"pool": len(pool), "within": len(near), "shown": shown, "groups": by.most_common(8), "closest": ranked[0] if ranked else None,
            "closest_distance": dist(ranked[0]) if ranked else None,
            "range_o2": (min(r["o2"] for r in pool), max(r["o2"] for r in pool)) if pool else None,
            "range_p": (min(r["p_psi"] for r in pool), max(r["p_psi"] for r in pool)) if pool else None}


def outcomes(catalog: Catalog, scope: Scope) -> dict:
    pool = select(catalog, Scope(**{**scope.__dict__, "with_outcome": True}))
    counts = Counter(r["outcome"] for r in pool)
    n = len(pool)
    shares = {o: (c, c / n, *wilson(c, n)) for o, c in counts.items()}
    return {"n": n, "counts": counts, "shares": shares, "rows": pool, "investigations": sorted({r["name"] for r in pool})}


def threshold(catalog: Catalog, scope: Scope, target: str, variable: str, direction: str = "lowest") -> dict | None:
    """The lowest (or highest) oxygen or pressure at which the target outcome was seen, and what happened on either side of it."""
    pool = [r for r in select(catalog, Scope(**{**scope.__dict__, "with_outcome": True})) if positive(r, target) is not None]
    if not pool:
        return None
    key = (lambda r: r["o2"]) if variable == "o2" else (lambda r: r["p_atm"])
    hits = [r for r in pool if positive(r, target)]
    if not hits:
        return {"found": False, "n": len(pool), "pool": pool}
    edge = (min if direction == "lowest" else max)(key(r) for r in hits)
    at_edge = [r for r in hits if abs(key(r) - edge) < 1e-9]
    beyond = [r for r in pool if (key(r) < edge - 1e-9 if direction == "lowest" else key(r) > edge + 1e-9)]
    inside = [r for r in pool if r not in beyond]
    return {"found": True, "edge": edge, "variable": variable, "direction": direction, "at_edge": at_edge, "n": len(pool), "positives": len(hits),
            "beyond": len(beyond), "beyond_positive": sum(1 for r in beyond if positive(r, target)), "inside": len(inside),
            "inside_positive": sum(1 for r in inside if positive(r, target)), "pool": pool}


def profile(catalog: Catalog, scope: Scope, target: str, variable: str = "o2") -> dict | None:
    """How the share of tests with the target outcome changes across oxygen (bands of 5 points) or pressure (bands of 1 atm)."""
    pool = [r for r in select(catalog, Scope(**{**scope.__dict__, "with_outcome": True})) if positive(r, target) is not None]
    if not pool:
        return None
    width = 0.05 if variable == "o2" else 1.0
    val = (lambda r: r["o2"]) if variable == "o2" else (lambda r: r["p_atm"])
    bands = defaultdict(list)
    for r in pool:
        bands[math.floor(val(r) / width + 1e-9)].append(r)
    out = []
    for b in sorted(bands):
        rows = bands[b]
        k = sum(1 for r in rows if positive(r, target))
        lo, hi = wilson(k, len(rows))
        out.append({"low_edge": b * width, "high_edge": (b + 1) * width, "n": len(rows), "hits": k, "share": k / len(rows), "low": lo, "high": hi})
    return {"bands": out, "n": len(pool), "hits": sum(b["hits"] for b in out), "rows": pool, "variable": variable}


def by_fuel(rows: list[dict], target: str | None = None) -> list[dict]:
    groups = defaultdict(list)
    for r in rows:
        groups[r["fuel_key"] or r["fuel"] or "no fuel named"].append(r)
    out = []
    for g, rs in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        hit = sum(1 for r in rs if (positive(r, target) if target else False))
        out.append({"fuel": g, "n": len(rs), "hits": hit, "outcomes": Counter(r["outcome"] for r in rs)})
    return out


def compare(catalog: Catalog, scope: Scope, target: str, by: str, groups: list[str] | None = None) -> dict | None:
    pool = [r for r in select(catalog, Scope(**{**scope.__dict__, "with_outcome": True})) if positive(r, target) is not None]
    if not pool:
        return None
    key = {"diluent": lambda r: r["diluent"], "fuel": lambda r: r["fuel_key"] or r["fuel"], "investigation": lambda r: r["name"]}[by]
    grouped = defaultdict(list)
    for r in pool:
        grouped[key(r)].append(r)
    keep = [g for g in (groups or sorted(grouped, key=lambda g: -len(grouped[g]))) if g in grouped]
    out = []
    for g in keep:
        rows = grouped[g]
        k = sum(1 for r in rows if positive(r, target))
        lo, hi = wilson(k, len(rows))
        out.append({"group": g, "n": len(rows), "hits": k, "share": k / len(rows), "low": lo, "high": hi, "o2": (min(r["o2"] for r in rows), max(r["o2"] for r in rows)),
                    "p_psi": (min(r["p_psi"] for r in rows), max(r["p_psi"] for r in rows))})
    return {"groups": out, "n": len(pool), "by": by}
