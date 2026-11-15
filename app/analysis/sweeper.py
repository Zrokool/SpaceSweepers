"""Flame Sweeper: what happened at each oxygen and pressure that PSI tested, and where nothing has been tested.

For one experiment family at a time (never pooled), every test that records oxygen, pressure and an outcome
becomes a point on an oxygen x pressure grid. A cell with tests is "revealed": it shows how many tests and what
share of flames kept burning. A cell with none stays "fog".

Prediction is held to a rule. A simple, transparent model (logistic regression on oxygen and pressure) is fitted
and cross-validated; its estimates for untested cells are shown ONLY if it beats guessing by a clear margin, and
only inside the tested range next to tested cells. Otherwise only observed counts are shown. No SI, no dependency.
"""

from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict

from app.analysis.habitats import in_box
from app.analysis.rank import NEAR_O2, NEAR_PSI

ATM_PSI = 14.695949
USABLE = ("ok", "approx", "range")
O2_STEP, P_STEP = 0.02, 0.25            # grid: 0.02 mole fraction of oxygen, 0.25 atm
FOLDS, SEED = 10, 7
MIN_SKILL_GAIN, MIN_AUC = 0.05, 0.70     # the skill gate: accuracy beats the baseline by 5 points and AUC is at least 0.70
MIN_TESTS, MIN_PER_CLASS = 60, 15        # too few tests, or too few of one outcome, and no model is fitted
FLAG_MIN_TESTS = 3                       # a flag needs at least this many tests, all with the same outcome

FAMILIES = {
    "droplet_end_state": {
        "label": "Droplet flames: how they ended",
        "short": "FLEX droplets",
        "outcome_kind": "end_state",
        "ambient_only": False,
        "sustained": ("completed", "disrupted"),         # the flame burned until the test ended
        "gone": ("extinguished",),                       # the flame went out before the test ended
        "excluded": (),
        "sustained_label": "burned until the test ended",
        "gone_label": "went out by itself",
        "definition": ("A burning fuel droplet in a chamber of known gas. 'Went out by itself' = PSI's 'Extinction'. "
                       "'Burned until the test ended' = 'Completion' (fuel used up) or 'Disruption' (the droplet was disturbed while "
                       "burning). Both are counted together and the three are shown separately in each cell."),
    },
    "gas_ignition": {
        "label": "Gas flames: did a hot flame light",
        "short": "CFI-G ignition",
        "outcome_kind": "ignition",
        "ambient_only": True,                            # only tests whose oxygen is the chamber atmosphere can sit on this grid
        "sustained": ("ignited",),
        "gone": ("no_ignition",),
        "excluded": ("flash",),                          # a flash is neither; it is counted and shown, not modelled
        "sustained_label": "a hot flame lit",
        "gone_label": "no hot flame",
        "definition": ("A gas fuel burned from a spherical burner into a chamber atmosphere. 'A hot flame lit' = PSI's 'Hot ignition: yes'. "
                       "Inverse-flame tests are left out: their oxygen is the burner stream, not the chamber. Brief flashes are counted but not modelled."),
    },
    "droplet_reignition": {
        "label": "Droplet cool flames: did the flame reignite",
        "short": "CFI reignition",
        "outcome_kind": "reignition",
        "ambient_only": False,
        "sustained": ("reignited",),
        "gone": ("no_reignition",),
        "excluded": (),
        "sustained_label": "the flame reignited",
        "gone_label": "no reignition",
        "simulation_fuels": ("dodecane",),                # PSI-117's simulations of the same fuel can be shown as a coverage strip
        "definition": ("A burning fuel droplet in a chamber of known gas (dodecane blends, farnesane). 'The flame reignited' = the lab's own count of "
                       "reignitions is above zero: the hot flame went out, a cool flame followed, and the hot flame came back. 'No reignition' = a count of zero. "
                       "Tests with no reignition count are left out, not counted as zero."),
    },
    "solid_burn": {
        "label": "Solid samples: did it burn (from lab notes)",
        "short": "BASS burn",
        "outcome_kind": "burn",
        "ambient_only": True,
        "layer": "document",                              # outcomes read from the lab's free-text notes, never from a table column
        "sustained": ("burned",),
        "gone": ("no_ignition",),
        "excluded": (),
        "sustained_label": "the notes say it burned",
        "gone_label": "the notes say it did not ignite",
        "definition": ("Solid material samples burned in a cabin-like atmosphere (BASS). The outcome is not a table column: SI pointed at the sentence in the "
                       "lab's own test notes and fixed rules read it. Samples whose notes are unclear, or contradict themselves, are left out and counted. "
                       "These are observed counts only: no model is fitted and nothing here enters the statistics of the table-based families."),
    },
}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson interval for a share k/n."""
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


# ------------------------------------------------------------------ the tests behind a family
def _value(test: dict, variable: str):
    v = test["values"].get(variable)
    return v["value"] if v and v["flag"] in USABLE else None


def collect(catalog, family: str, fuel: str | None = None, diluent: str | None = None) -> tuple[list[dict], dict]:
    """Usable tests for a family, and how many were left out for which reason (nothing is dropped silently)."""
    fam = FAMILIES[family]
    document = fam.get("layer") == "document"
    rows, dropped = [], Counter()
    for t in catalog.tests:
        if t.get("outcome_kind") != fam["outcome_kind"]:
            continue
        if document and (t["values"].get("outcome") or {}).get("flag") != "document_text":
            continue                                      # a document family reads only the document layer
        if fam["ambient_only"] and t["o2_role"] != "ambient":
            dropped["oxygen is the burner stream, not the chamber"] += 1
            continue
        o2, p_psi, cls = _value(t, "o2_fraction"), _value(t, "pressure_psi"), (t["values"]["outcome"]["value"] if document else _value(t, "outcome"))
        if o2 is None or p_psi is None:
            dropped["no usable oxygen or pressure value"] += 1
            continue
        if cls is None:
            dropped["no outcome recorded"] += 1
            continue
        name = (_value(t, "fuel") or "unknown")
        he, co2 = _value(t, "he_fraction") or 0.0, _value(t, "co2_fraction") or 0.0
        dil = "helium" if he > 0 else "carbon dioxide" if co2 > 0 else "nitrogen only"
        if fuel and fuel.lower() not in str(name).lower():
            continue
        if diluent and diluent != dil:
            continue
        rows.append({"psi": t["investigation"], "file": t["file"], "row": t["row"], "test_id": t["test_id"], "o2": o2, "p_atm": p_psi / ATM_PSI,
                     "fuel": str(name), "diluent": dil, "outcome": cls, "diameter": _value(t, "droplet_diameter_mm"),
                     "source": "document" if document else "table", "quote": t.get("outcome_quote")})
    return rows, dict(dropped)


def label(row: dict, fam: dict) -> int | None:
    """1 = the flame kept going, 0 = it went out / did not light, None = counted but not modelled."""
    if row["outcome"] in fam["sustained"]:
        return 1
    if row["outcome"] in fam["gone"]:
        return 0
    return None


# ------------------------------------------------------------------ a small logistic regression (IRLS), no dependency
def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        m[c], m[piv] = m[piv], m[c]
        d = m[c][c] or 1e-12
        m[c] = [x / d for x in m[c]]
        for r in range(n):
            if r != c:
                f = m[r][c]
                m[r] = [x - f * y for x, y in zip(m[r], m[c])]
    return [m[i][n] for i in range(n)]


def _inverse(a: list[list[float]]) -> list[list[float]]:
    n = len(a)
    return [list(col) for col in zip(*[_solve(a, [1.0 if i == j else 0.0 for i in range(n)]) for j in range(n)])]


def _sigmoid(z: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))


def fit(X: list[list[float]], y: list[int], l2: float = 1.0, iters: int = 25) -> dict:
    """Logistic regression on standardized features. Returns weights, scaling and the Hessian (for intervals)."""
    d = len(X[0])
    mu = [sum(r[j] for r in X) / len(X) for j in range(d)]
    sd = [(sum((r[j] - mu[j]) ** 2 for r in X) / len(X)) ** 0.5 or 1.0 for j in range(d)]
    Z = [[1.0] + [(r[j] - mu[j]) / sd[j] for j in range(d)] for r in X]
    w = [0.0] * (d + 1)
    h = [[0.0] * (d + 1) for _ in range(d + 1)]
    for _ in range(iters):
        grad = [0.0] * (d + 1)
        h = [[0.0] * (d + 1) for _ in range(d + 1)]
        for z, yi in zip(Z, y):
            p = _sigmoid(sum(a * b for a, b in zip(w, z)))
            wt = max(p * (1 - p), 1e-6)
            for i in range(d + 1):
                grad[i] += (p - yi) * z[i]
                for j in range(d + 1):
                    h[i][j] += wt * z[i] * z[j]
        for i in range(1, d + 1):
            grad[i] += l2 * w[i]
            h[i][i] += l2
        step = _solve(h, grad)
        w = [a - b for a, b in zip(w, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return {"w": w, "mu": mu, "sd": sd, "h": h}


def predict(model: dict, x: list[float]) -> float:
    z = [1.0] + [(x[j] - model["mu"][j]) / model["sd"][j] for j in range(len(x))]
    return _sigmoid(sum(a * b for a, b in zip(model["w"], z)))


def predict_interval(model: dict, x: list[float], covariance: list[list[float]]) -> tuple[float, float, float]:
    """Estimate and 90% interval (delta method on the log-odds)."""
    z = [1.0] + [(x[j] - model["mu"][j]) / model["sd"][j] for j in range(len(x))]
    eta = sum(a * b for a, b in zip(model["w"], z))
    var = sum(z[i] * covariance[i][j] * z[j] for i in range(len(z)) for j in range(len(z)))
    se = math.sqrt(max(var, 0.0))
    return _sigmoid(eta), _sigmoid(eta - 1.645 * se), _sigmoid(eta + 1.645 * se)


def auc(scores: list[tuple[float, int]]) -> float:
    pos = [s for s, y in scores if y == 1]
    neg = [s for s, y in scores if y == 0]
    if not pos or not neg:
        return 0.5
    return sum((a > b) + 0.5 * (a == b) for a in pos for b in neg) / (len(pos) * len(neg))


def cross_validate(X: list[list[float]], y: list[int]) -> dict:
    """10-fold cross-validation with a fixed seed: accuracy, AUC and the accuracy of always guessing the commoner outcome."""
    idx = list(range(len(y)))
    random.Random(SEED).shuffle(idx)
    folds = [idx[i::FOLDS] for i in range(FOLDS)]
    correct, scores = 0, []
    for fold in folds:
        held = set(fold)
        train = [i for i in idx if i not in held]
        model = fit([X[i] for i in train], [y[i] for i in train])
        for i in fold:
            p = predict(model, X[i])
            scores.append((p, y[i]))
            correct += (p >= 0.5) == (y[i] == 1)
    baseline = max(sum(y), len(y) - sum(y)) / len(y)
    return {"accuracy": correct / len(y), "auc": auc(scores), "baseline": baseline}


def skill(rows: list[dict], fam: dict) -> tuple[dict, dict | None]:
    """The skill check and, when it passes, the model fitted on every usable test."""
    data = [(r, label(r, fam)) for r in rows]
    data = [(r, y) for r, y in data if y is not None]
    n, positives = len(data), sum(y for _, y in data)
    info = {"tests": n, "folds": FOLDS, "features": ["oxygen", "pressure"], "passes": False, "gate":
            f"Estimates are shown only if cross-validated accuracy beats always guessing the commoner outcome by {MIN_SKILL_GAIN:.0%} and AUC is at least {MIN_AUC:.2f}."}
    if n < MIN_TESTS or min(positives, n - positives) < MIN_PER_CLASS:
        info["reason"] = (f"Only {n} usable tests ({positives} of one outcome, {n - positives} of the other): "
                          f"at least {MIN_TESTS} tests and {MIN_PER_CLASS} of each outcome are needed to fit a model.")
        return info, None
    X = [[r["o2"], r["p_atm"]] for r, _ in data]
    y = [y for _, y in data]
    cv = cross_validate(X, y)
    info.update({k: round(v, 3) for k, v in cv.items()})
    info["passes"] = cv["accuracy"] >= cv["baseline"] + MIN_SKILL_GAIN and cv["auc"] >= MIN_AUC
    info["reason"] = (f"Accuracy {cv['accuracy']:.0%} against {cv['baseline']:.0%} for always guessing the commoner outcome, AUC {cv['auc']:.2f}: "
                      + ("the model beats guessing, so estimates are shown for untested cells inside the tested range."
                         if info["passes"] else "the model does not beat guessing by enough, so only observed counts are shown."))
    return info, (fit(X, y) if info["passes"] else None)


# ------------------------------------------------------------------ the grid
def _axes(rows: list[dict]) -> dict:
    o2s, ps = [r["o2"] for r in rows], [r["p_atm"] for r in rows]
    o_lo = math.floor(min(o2s) / O2_STEP + 1e-9) * O2_STEP
    o_hi = math.ceil(max(o2s) / O2_STEP + 1e-9) * O2_STEP
    p_lo = math.floor(min(ps) / P_STEP + 1e-9) * P_STEP
    p_hi = math.ceil(max(ps) / P_STEP + 1e-9) * P_STEP
    return {"o2": {"min": round(o_lo, 4), "max": round(max(o_hi, o_lo + O2_STEP), 4), "step": O2_STEP, "n": max(1, round((o_hi - o_lo) / O2_STEP))},
            "p_atm": {"min": round(p_lo, 4), "max": round(max(p_hi, p_lo + P_STEP), 4), "step": P_STEP, "n": max(1, round((p_hi - p_lo) / P_STEP))}}


def _pressure_span(text: str) -> tuple[str, list[float]] | None:
    """A simulated pressure as written ("1", "0.5 - 3.0", "0.5 and 5.0"): ("point" | "range" | "points", [atm])."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text or "")]
    if not nums:
        return None
    if re.search(r"\d\s*-\s*\d", text):
        return "range", [min(nums), max(nums)]
    return ("point", nums) if len(nums) == 1 else ("points", sorted(nums))


def simulation_strips(catalog, fam: dict) -> list[dict]:
    """Where a modelling study's simulations of the same fuel lie along the pressure axis. Metadata only: no simulated result is shown."""
    out = []
    for inv in catalog.ordered():
        sim = inv.get("simulated_data")
        for row in (sim or {}).get("rows", []):
            if not any(f in (row.get("Fuel") or "").lower() for f in fam.get("simulation_fuels", ())):
                continue
            span = _pressure_span(row.get("P (atm)", ""))
            if span:
                out.append({"psi": inv["id"], "name": inv["name"], "label": row.get("Data File"), "fuel": row.get("Fuel"), "kind": span[0], "p_atm": span[1],
                            "droplet_mm": row.get("do (mm)"), "reference": (row.get("Reference") or "").strip(), "figure": row.get("Figure")})
    return out


def sweep(catalog, family: str, habitat: dict | None, fuel: str | None = None, diluent: str | None = None) -> dict:
    fam = FAMILIES[family]
    rows, dropped = collect(catalog, family, fuel, diluent)
    out = {"family": family, "label": fam["label"], "definition": fam["definition"], "sustained_label": fam["sustained_label"],
           "simulations": simulation_strips(catalog, fam),
           "gone_label": fam["gone_label"], "tests": len(rows), "dropped": dropped,
           "investigations": sorted({r["psi"] for r in rows}, key=lambda s: int(s.split("-")[1])), "filters": {"fuel": fuel, "diluent": diluent},
           # With the Habitat view off no habitat is used anywhere in this result: no box, no habitat sentence, no habitat-weighted suggestions.
           "habitat": ({"label": habitat.get("label"), "o2": habitat["o2"], "p_atm": [habitat["pressure_psi"][0] / ATM_PSI, habitat["pressure_psi"][1] / ATM_PSI]}
                       if habitat else None)}
    if not rows:
        return {**out, "axes": None, "cells": [], "skill": {"passes": False, "reason": "No usable tests for this selection."}, "patterns": [], "next": []}
    axes = _axes(rows)
    if fam.get("layer") == "document":                  # observed counts only: a model never sees document-derived outcomes
        info, model = {"tests": len(rows), "passes": False, "reason": "These outcomes were read from lab notes, so only observed counts are shown; no model is fitted."}, None
    else:
        info, model = skill(rows, fam)
    covariance = _inverse(model["h"]) if model else None
    cells = {}
    for r in rows:
        i = min(axes["o2"]["n"] - 1, int((r["o2"] - axes["o2"]["min"]) / O2_STEP + 1e-9))
        j = min(axes["p_atm"]["n"] - 1, int((r["p_atm"] - axes["p_atm"]["min"]) / P_STEP + 1e-9))
        cells.setdefault((i, j), []).append(r)
    lo_o, hi_o = min(r["o2"] for r in rows), max(r["o2"] for r in rows)
    lo_p, hi_p = min(r["p_atm"] for r in rows), max(r["p_atm"] for r in rows)
    grid = []
    for j in range(axes["p_atm"]["n"]):
        for i in range(axes["o2"]["n"]):
            o2_lo, p_lo = axes["o2"]["min"] + i * O2_STEP, axes["p_atm"]["min"] + j * P_STEP
            cell = {"i": i, "j": j, "o2": [round(o2_lo, 4), round(o2_lo + O2_STEP, 4)], "p_atm": [round(p_lo, 4), round(p_lo + P_STEP, 4)],
                    "n": 0, "counts": {}, "state": "fog", "flag": False, "share": None, "estimate": None, "tests": []}
            members = cells.get((i, j), [])
            if members:
                modelled = [(m, label(m, fam)) for m in members if label(m, fam) is not None]
                k, n = sum(y for _, y in modelled), len(modelled)
                lo, hi = wilson(k, n)
                cell.update({"n": len(members), "state": "revealed", "counts": dict(Counter(m["outcome"] for m in members)),
                             "share": round(k / n, 3) if n else None, "share_ci": [round(lo, 3), round(hi, 3)] if n else None, "modelled": n,
                             "flag": n >= FLAG_MIN_TESTS and k == n,
                             "tests": [{"psi": m["psi"], "file": m["file"], "row": m["row"], "test_id": m["test_id"], "outcome": m["outcome"],
                                        "o2": round(m["o2"], 4), "p_atm": round(m["p_atm"], 3), "fuel": m["fuel"], "diluent": m["diluent"],
                                        "source": m["source"], "quote": m["quote"]} for m in members[:40]]})
            grid.append(cell)
    by = {(c["i"], c["j"]): c for c in grid}
    for c in grid:   # a model estimate only for an untested cell, inside the tested range, beside a tested cell
        if c["state"] == "fog" and model:
            mid_o, mid_p = sum(c["o2"]) / 2, sum(c["p_atm"]) / 2
            near = any(by.get((c["i"] + a, c["j"] + b), {}).get("state") == "revealed" for a in (-1, 0, 1) for b in (-1, 0, 1))
            if near and lo_o <= mid_o <= hi_o and lo_p <= mid_p <= hi_p:
                p, plo, phi = predict_interval(model, [mid_o, mid_p], covariance)
                c["estimate"] = {"share": round(p, 3), "low": round(plo, 3), "high": round(phi, 3)}
    out.update({"axes": axes, "cells": grid, "skill": info, "layer": fam.get("layer", "table")})
    out["patterns"] = patterns(rows, fam, habitat)
    out["next"] = next_tests(grid, axes, habitat)
    return out


# ------------------------------------------------------------------ patterns and suggestions, all computed
def patterns(rows: list[dict], fam: dict, habitat: dict | None) -> list[dict]:
    """Plain facts read straight off the tests. Each has an id so a sentence can cite it."""
    modelled = [(r, label(r, fam)) for r in rows if label(r, fam) is not None]
    out = []
    if not modelled:
        return out
    n = len(modelled)
    by_o2 = defaultdict(list)
    for r, y in modelled:
        by_o2[round(r["o2"], 2)].append(y)
    levels = sorted(by_o2)
    # the lowest oxygen above which no test ended any way other than "kept burning" (at least 8 tests up there)
    for lvl in levels:
        above = [y for r, y in modelled if round(r["o2"], 2) >= lvl]
        if len(above) >= 8 and all(above):
            out.append({"id": "P1", "kind": "ceiling",
                        "text": f"At {lvl:.2f} oxygen or more, the outcome was \"{fam['sustained_label']}\" in all {len(above)} tests and \"{fam['gone_label']}\" in none.",
                        "numbers": {"o2": lvl, "tests": len(above)}})
            break
    low = [y for r, y in modelled if r["o2"] <= 0.15]
    if len(low) >= 8:
        gone = sum(1 for y in low if y == 0)
        out.append({"id": "P2", "kind": "low_oxygen", "text": f"At 0.15 oxygen or less, the outcome was \"{fam['gone_label']}\" in {gone} of {len(low)} tests.",
                    "numbers": {"o2": 0.15, "tests": len(low), "gone": gone}})
    dil = defaultdict(list)
    for r, y in modelled:
        dil[r["diluent"]].append(y)
    if len(dil) > 1 and all(len(v) >= 15 for v in dil.values()):
        parts = "; ".join(f"{d}: {sum(1 for y in v if y == 0)} of {len(v)}" for d, v in sorted(dil.items()))
        out.append({"id": "P3", "kind": "diluent", "text": f"Tests with the outcome \"{fam['gone_label']}\", by what else was in the chamber gas: {parts}. This compares observed counts only; the tests did not vary one gas at a time.",
                    "numbers": {d: [sum(1 for y in v if y == 0), len(v)] for d, v in dil.items()}})
    # the lowest pressure above which the outcome appears: "at 1.25 atm or less, none of 88 tests ..."
    by_p = defaultdict(list)
    for r, y in modelled:
        by_p[round(r["p_atm"] * 4) / 4].append(y)
    best = None
    for level in sorted(by_p)[:-1]:                              # the highest pressure that still has no positive outcome at or below it
        low = [y for p, ys in by_p.items() if p <= level for y in ys]
        high = [y for p, ys in by_p.items() if p > level for y in ys]
        if len(low) >= 8 and sum(low) == 0 and sum(high) > 0:
            best = (level, low, high)
    if best:
        level, low, high = best
        out.append({"id": "P5", "kind": "floor",
                    "text": (f"At {level:g} atm or less, the outcome was \"{fam['sustained_label']}\" in none of {len(low)} tests; above {level:g} atm it was in "
                             f"{sum(high)} of {len(high)}."),
                    "numbers": {"p_atm": level, "below": len(low), "above_yes": sum(high), "above": len(high)}})
    if habitat is not None:                      # with the Habitat view off there is no habitat sentence at all
        h = {"o2": habitat["o2"], "pressure_psi": habitat["pressure_psi"]}
        box = [(r, y) for r, y in modelled if in_box(h, r["o2"], r["p_atm"] * ATM_PSI)]
        near = [(r, y) for r, y in modelled if (r, y) not in box and h["o2"][0] - NEAR_O2 <= r["o2"] <= h["o2"][1] + NEAR_O2
                and h["pressure_psi"][0] - NEAR_PSI <= r["p_atm"] * ATM_PSI <= h["pressure_psi"][1] + NEAR_PSI]
        text = f"{len(box)} of {n} usable tests lie inside the selected habitat's oxygen and pressure box"
        text += f"; the outcome was \"{fam['sustained_label']}\" in {sum(y for _, y in box)} of them" if box else ""
        if near:
            nearest = sorted(r["p_atm"] * ATM_PSI for r, _ in near)
            text += (f". {len(near)} more lie within {NEAR_O2:g} oxygen and {NEAR_PSI:g} psi of it (their pressures run {nearest[0]:.1f} to {nearest[-1]:.1f} psi); "
                     f"the outcome was \"{fam['sustained_label']}\" in {sum(y for _, y in near)} of those")
        out.append({"id": "P4", "kind": "habitat", "text": text + ".", "numbers": {"inside": len(box), "near": len(near), "tests": n}})
    if fam.get("layer") == "document":
        yes = sum(y for _, y in modelled)
        out.append({"id": "P6", "kind": "document_layer",
                    "text": (f"Read from the lab's test notes: \"{fam['sustained_label']}\" for {yes} of {n} samples with a clear outcome; "
                             f"\"{fam['gone_label']}\" for {n - yes}. These are the notes' words, not table values, and are not used in any model."),
                    "numbers": {"burned": yes, "tests": n}})
    return out


def next_tests(grid: list[dict], axes: dict, habitat: dict | None, limit: int = 5) -> list[dict]:
    """Untested cells worth testing: beside tested cells, preferably where neighbours disagree or inside the habitat box."""
    by = {(c["i"], c["j"]): c for c in grid}
    h_o, h_p = (habitat["o2"], [habitat["pressure_psi"][0] / ATM_PSI, habitat["pressure_psi"][1] / ATM_PSI]) if habitat else (None, None)
    out = []
    for c in grid:
        if c["state"] != "fog":
            continue
        nb = [by[(c["i"] + a, c["j"] + b)] for a in (-1, 0, 1) for b in (-1, 0, 1) if (a or b) and (c["i"] + a, c["j"] + b) in by]
        seen = [x for x in nb if x["state"] == "revealed" and x["share"] is not None]
        if not seen:
            continue
        mixed = min(x["share"] for x in seen) < 0.5 <= max(x["share"] for x in seen) or (max(x["share"] for x in seen) - min(x["share"] for x in seen) >= 0.5)
        mid_o, mid_p = sum(c["o2"]) / 2, sum(c["p_atm"]) / 2
        inside = bool(habitat) and h_o[0] <= mid_o <= h_o[1] and h_p[0] <= mid_p <= h_p[1]
        score = len(seen) + (2 if mixed else 0) + (3 if inside else 0)
        why = [f"{len(seen)} tested neighbouring cell{'s' if len(seen) != 1 else ''}"] + (["neighbours disagree"] if mixed else []) + (["inside the habitat box"] if inside else [])
        out.append({"i": c["i"], "j": c["j"], "o2": c["o2"], "p_atm": c["p_atm"], "score": score, "why": ", ".join(why)})
    out.sort(key=lambda x: (-x["score"], x["o2"][0], x["p_atm"][0]))
    return out[:limit]
