"""Read a user's scenario and answer it from the tests: the code-first analyst behind SI Insights. No SI is needed to answer.

A scenario is what a researcher or engineer actually asks: a fuel or material, a gas mixed with oxygen, an oxygen level and a
pressure, and what they want to know (the nearest tested conditions, what happened, the lowest oxygen where it burned, how two
gases compare). Fixed patterns read the question; the analyses in app/analysis/queries.py compute the answer; every sentence is
a template filled with computed numbers, and the table shows each test with its file and row.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.analysis import queries as q
from app.analysis.rank import NEAR_O2, NEAR_PSI
from app.catalog import Catalog

# What the user wants to know, found by fixed patterns, strongest first.
GOAL_PATTERNS = [
    ("profile", r"\b(how (?:does|do|is|are) [^.?!]{0,60}(?:affect\w*|influenc\w*|depend\w*|change\w*|vary|varies)|effects? of|role of|trend|relationship between|summari[sz]e how)\b"),
    ("threshold", r"\b(lowest|minimum|minimal|least|highest|maximum|upper limit|at what|start(?:s)? to|begin(?:s)? to|onset|threshold|limit(?:ing)?)\b"),
    ("compare", r"\b(compar\w*|versus|vs\.?|better|worse|difference between|differ\w*|more effective|less effective)\b"),
    ("nearest", r"\b(closest|nearest|similar (?:conditions|atmosphere)|designing|design(?:ed)? (?:for|at)|operating at|our (?:habitat|cabin|vehicle|rover)|tested conditions)\b"),
    ("outcomes", r"\b(what happened|outcomes?|results?|how often|how many (?:\w+ ){0,3}(?:burn|ignit|extinguish|went out)|did (?:\w+ ){0,3}(?:burn|ignite|extinguish))\b"),
]
TARGET_PATTERNS = [
    ("reignite", r"\bre-?ignit\w*"),
    ("extinguish", r"\b(extinguish\w*|went out|goes out|suppress\w*|quench\w*|extinction)\b"),
    ("ignite", r"\bignit\w*"),
    ("burn", r"\b(burn(?:ed|s|t|ing)?|kept burning|sustain\w*|combust\w*)\b"),
]
DILUENT_PATTERNS = [("helium", r"\bhelium\b|\bhe\b(?!\w)"), ("carbon dioxide", r"\bcarbon dioxide\b|\bco2\b|co₂"), ("nitrogen only", r"\bnitrogen\b|\bn2\b")]
FAMILY = {"end_state": "droplet_end_state", "ignition": "gas_ignition", "reignition": "droplet_reignition", "burn": "solid_burn"}
KIND_OF_TARGET = {"reignite": "reignition", "ignite": "ignition"}


@dataclass
class Scenario:
    goal: str                                        # threshold | compare | nearest | outcomes
    scope: q.Scope = field(default_factory=q.Scope)
    target: str | None = None                        # burn | extinguish | ignite | reignite
    variable: str = "o2"                             # o2 | p (what a threshold is measured in)
    direction: str = "lowest"
    compare_by: str | None = None
    compare_groups: list[str] | None = None
    o2_point: float | None = None
    p_point_psi: float | None = None
    asked: str = ""
    inherited: list[str] = field(default_factory=list)      # what this follow-up kept from the last question
    changed: list[str] = field(default_factory=list)        # and what the user changed


def _mentions(text: str, patterns) -> list[str]:
    return [name for name, pat in patterns if re.search(pat, text, re.I)]


def _fuels(text: str) -> list[str]:
    found = []
    for word, key in q.FUEL_WORDS.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text, re.I) and key not in found:
            found.append(key)
    return found


FOLLOW = re.compile(r"^\s*(and|what about|how about|now|same but|instead|but|then|also|what if)\b", re.I)
GOAL_PHRASE = {"threshold": "the lowest or highest value", "compare": "the comparison", "nearest": "the nearest tested conditions", "outcomes": "what happened", "profile": "how it changes"}
TARGET_PHRASE = {"burn": "it burned", "extinguish": "it went out", "ignite": "it lit", "reignite": "it reignited"}


def _inherit(text: str, frame, ctx: dict) -> dict | None:
    """A follow-up ("and for heptane?", "what about 2 atm?") keeps the last question's goal and changes only what the user changed."""
    own_goal = next((g for g, pat in GOAL_PATTERNS if re.search(pat, text, re.I)), None)
    fuels, dils, targets = _fuels(text), _mentions(text, DILUENT_PATTERNS), _mentions(text, TARGET_PATTERNS)
    new_o2 = (frame.o2['min'] + frame.o2['max']) / 2 if frame.o2 and frame.o2['min'] is not None and frame.o2['max'] is not None else None
    new_p = (frame.pressure['min'] + frame.pressure['max']) / 2 if frame.pressure and frame.pressure['min'] is not None and frame.pressure['max'] is not None else None
    has_new = bool(fuels or dils or targets or new_o2 is not None or new_p is not None)
    follow = bool(FOLLOW.match(text)) or (own_goal is None and len(text.split()) <= 10 and has_new)
    if not follow or not ctx.get("goal") or not (has_new or own_goal):
        return None
    goal = own_goal or ctx["goal"]
    if goal == "compare" and dils and not own_goal:
        goal = "outcomes"                                   # "what about carbon dioxide?" after a comparison asks what happened with it
    merged = {"goal": goal, "target": (targets[0] if targets else ctx.get("target")), "variable": ctx.get("variable"),
              "fuel": fuels[0] if fuels else ctx.get("fuel"), "diluent": dils[0] if dils else ctx.get("diluent"),
              "o2": new_o2 if new_o2 is not None else ctx.get("o2"), "p_psi": new_p if new_p is not None else ctx.get("p_psi")}
    changed = [n for n, v in (("fuel", fuels), ("gas", dils), ("oxygen", new_o2 is not None), ("pressure", new_p is not None), ("outcome", targets)) if v]
    kept = [n for n, k in (("goal", not own_goal), ("fuel", ctx.get("fuel") and not fuels), ("gas", ctx.get("diluent") and not dils), ("oxygen", ctx.get("o2") is not None and new_o2 is None),
                          ("pressure", ctx.get("p_psi") is not None and new_p is None), ("outcome", ctx.get("target") and not targets)) if k]
    merged["_kept"], merged["_changed"] = kept, changed
    return merged


def read(question: str, frame, structured: dict | None = None, context: dict | None = None) -> Scenario | None:
    """A Scenario when the question (or the scenario form) states something the tests can answer, else None."""
    text = " ".join((question or "").split())
    kept = changed = []
    if context and not structured:
        merged = _inherit(text, frame, context)
        if merged:
            kept, changed = merged.pop("_kept"), merged.pop("_changed")
            structured = merged
    s = structured or {}
    goal = s.get("goal") or next((g for g, pat in GOAL_PATTERNS if re.search(pat, text, re.I)), None)
    fuels = [s["fuel"]] if s.get("fuel") else _fuels(text)
    dils = [s["diluent"]] if s.get("diluent") else _mentions(text, DILUENT_PATTERNS)
    o2 = (s["o2"], s["o2"]) if s.get("o2") is not None else ((frame.o2["min"], frame.o2["max"]) if frame.o2 else None)
    p = (s["p_psi"], s["p_psi"]) if s.get("p_psi") is not None else ((frame.pressure["min"], frame.pressure["max"]) if frame.pressure else None)
    targets = [s["target"]] if s.get("target") else _mentions(text, TARGET_PATTERNS)
    target = targets[0] if targets else None
    # a question that states both an oxygen level and a pressure, with no other goal, asks about those conditions
    if goal is None and o2 and p and (o2[0] is not None and o2[1] is not None):
        goal = "nearest"
    if goal is None and (target or fuels or dils or frame.psi_ids) and (o2 or p or re.search(r"\b(data|tests?|materials?|what does psi have|burned|ignited)\b", text, re.I)):
        goal = "outcomes"                                    # the scenario names something the tests cover: show what happened
    if goal is None or (goal != "nearest" and not (target or fuels or dils)):
        return None
    scope = q.Scope(fuel=fuels[0] if len(fuels) == 1 else None, diluent=dils[0] if len(dils) == 1 else None, psi_ids=list(frame.psi_ids or []))
    sc = Scenario(goal=goal, scope=scope, target=target, asked=text, inherited=kept, changed=changed)
    if goal == "nearest":
        if not (o2 and p and o2[0] is not None and o2[1] is not None and p[0] is not None and p[1] is not None):
            return None
        sc.o2_point, sc.p_point_psi = (o2[0] + o2[1]) / 2, (p[0] + p[1]) / 2
        return sc
    scope.o2 = o2 if (o2 and goal != "threshold") else None
    scope.p_psi = p if (p and goal != "threshold") else None
    if goal == "compare":
        if structured and not dils:
            sc.compare_by, sc.compare_groups = "diluent", list(q.DILUENTS)
            sc.target = target or "extinguish"
            return sc
        if len(dils) >= 2 or (len(dils) == 1 and re.search(r"suppress|compar", text, re.I) and "nitrogen only" not in dils):
            sc.compare_by, sc.compare_groups = "diluent", [d for d in q.DILUENTS if d in dils or d == "nitrogen only"]
            scope.diluent = None
        elif len(fuels) >= 2:
            sc.compare_by, sc.compare_groups = "fuel", fuels
            scope.fuel = None
        elif len(frame.psi_ids or []) >= 2:
            sc.compare_by, sc.compare_groups = "investigation", None
        else:
            return None
        sc.target = target or ("extinguish" if re.search(r"suppress|extinguish|went out", text, re.I) else "burn")
    if goal == "profile":
        sc.target = target or "burn"
        sc.variable = "p" if re.search(r"\b(pressure|atm|psi)\b", text, re.I) and not re.search(r"\boxygen\b|\bo2\b", text, re.I) else "o2"
        if sc.target in KIND_OF_TARGET:
            scope.kind = KIND_OF_TARGET[sc.target]
    if goal == "threshold":
        sc.target = target or "burn"
        asks_pressure = bool(re.search(r"\b(pressure|atm|psi|kpa)\b", text, re.I)) and not re.search(r"\boxygen\b|\bo2\b", text, re.I)
        sc.variable = "p" if (s.get("variable") == "p" or asks_pressure or sc.target == "reignite") else "o2"
        sc.direction = "highest" if re.search(r"\b(highest|maximum|upper)\b", text, re.I) else "lowest"
        if sc.target in KIND_OF_TARGET:
            scope.kind = KIND_OF_TARGET[sc.target]
    return sc


# ------------------------------------------------------------------ the answer
def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _names(rows: list[dict], limit: int = 3) -> str:
    names = sorted({r["name"] for r in rows})
    return ", ".join(names[:limit]) + (f" and {len(names) - limit} more" if len(names) > limit else "")


def _caveats(catalog: Catalog, extra: list[str], rows: list[dict] | None = None) -> list[str]:
    if rows and any(r["document"] for r in rows):
        extra = [*extra, "BASS outcomes are read from the lab's own test notes (document text), not from a table column, and only for runs whose notes state clearly whether the sample burned."]
    mapped = len({r["psi"] for r in q.all_rows(catalog)})
    combustion = sum(1 for i in catalog.ordered() if i["is_combustion"])
    gone = q.left_out(catalog)
    if gone["burner_stream"] or gone["missing_condition"]:
        extra = [*extra, f"{gone['burner_stream'] + gone['missing_condition']} tests with a recorded outcome are not counted here: {gone['burner_stream']} have oxygen as the burner stream "
                         f"(not the chamber air) and {gone['missing_condition']} have no usable oxygen or pressure."]
    return [*extra, f"Only {mapped} of {combustion} combustion investigations have tests whose oxygen and pressure are mapped, so only those can be searched this way. "
            "Tests where oxygen is the burner stream, not the chamber air, are left out.",
            "This reports what NASA's tests showed at the conditions listed. It is research context, not a prediction for your design and not a safety rating."]


def _link(rows: list[dict], scope: q.Scope) -> dict | None:
    kinds = [k for k in dict.fromkeys(r["kind"] for r in rows) if k in FAMILY]
    if not kinds:
        return None
    link = {"kind": "sweeper", "label": "See these tests in the Flame Sweeper", "family": FAMILY[kinds[0]]}
    if kinds[0] == "end_state":
        fuel = (scope.fuel or "").lower()
        link["fuel"] = fuel if fuel in ("heptane", "methanol") else None
        link["diluent"] = scope.diluent
    return link


def analyse(catalog: Catalog, sc: Scenario) -> dict | None:
    """The answer card: sentences, key numbers, a table, caveats and links. None when no test can answer it."""
    card_table = None
    if sc.goal == "nearest":
        n = q.nearest(catalog, sc.o2_point, sc.p_point_psi, sc.scope)
        if not n["pool"]:
            return None
        where = f"{sc.o2_point * 100:.0f}% oxygen and {sc.p_point_psi:.1f} psi"
        c = n["closest"]
        if n["within"]:
            head = [f"{n['within']} of the {n['pool']} PSI tests with a known oxygen and pressure lie within {NEAR_O2 * 100:g} points of oxygen and {NEAR_PSI:g} psi of {where}."]
            if n["groups"]:
                head.append("They are mostly " + "; ".join(f"{g[0]} ({g[1]}): {g[2]} in {k} test{'s' if k != 1 else ''}" for g, k in [(x[0], x[1]) for x in n["groups"][:3]]) + ".")
        else:
            head = [f"No PSI test lies within {NEAR_O2 * 100:g} points of oxygen and {NEAR_PSI:g} psi of {where}. The closest is {c['name']} ({c['fuel'] or 'no fuel named'}) at "
                    f"{c['o2'] * 100:.0f}% oxygen and {c['p_psi']:.1f} psi: {q.OUTCOME_TEXT.get(c['outcome'], 'no outcome recorded')}."]
        head.append(f"Across all {n['pool']} tests, oxygen was tested from {n['range_o2'][0] * 100:.0f}% to {n['range_o2'][1] * 100:.0f}% and pressure from {n['range_p'][0]:.1f} to {n['range_p'][1]:.1f} psi.")
        metrics = [{"label": "tests nearby", "value": str(n["within"])}, {"label": "tests searched", "value": str(n["pool"])}]
        rows = n["shown"]
        title, extra = f"Tested conditions closest to {where}", ["Each test is shown at its own conditions, which differ from yours by the amounts in the table."]
    elif sc.goal == "threshold":
        t = q.threshold(catalog, sc.scope, sc.target, sc.variable, sc.direction)
        if not t:
            return None
        what = q.TARGET_TEXT[sc.target]
        subject = sc.scope.text()
        unit = (lambda v: f"{v * 100:.0f}% oxygen ({v:.2f} mole fraction)") if sc.variable == "o2" else (lambda v: f"{v:g} atm ({v * q.ATM_PSI:.1f} psi)")
        if not t["found"]:
            head = [f"In none of the {t['n']} tests ({subject}) did the flame end up as: {what}."]
            metrics, rows = [{"label": "tests", "value": str(t["n"])}], t["pool"]
        else:
            side = "below" if sc.direction == "lowest" else "above"
            head = [f"The {sc.direction} {'oxygen level' if sc.variable == 'o2' else 'pressure'} at which a flame {what} in these tests ({subject}) was {unit(t['edge'])}, seen in {_names(t['at_edge'])}."]
            head.append(f"{side.capitalize()} that, {t['beyond_positive']} of {t['beyond']} tests {what}. At or {'above' if sc.direction == 'lowest' else 'below'} it, {t['inside_positive']} of {t['inside']} did.")
            metrics = [{"label": f"{sc.direction} {'oxygen' if sc.variable == 'o2' else 'pressure (atm)'}", "value": f"{t['edge'] * 100:.0f}%" if sc.variable == "o2" else f"{t['edge']:g}"},
                       {"label": "tests", "value": str(t["n"])}]
            rows = sorted(t["pool"], key=lambda r: (r["o2"] if sc.variable == "o2" else r["p_atm"]), reverse=sc.direction == "highest")
            edge_rows = t["at_edge"]
            rows = edge_rows + [r for r in rows if r not in edge_rows]
        title, extra = f"{sc.direction.capitalize()} {'oxygen' if sc.variable == 'o2' else 'pressure'} where it {what}: {subject}", \
            ["The threshold is the lowest or highest value actually tested. The true limit may lie between the tested values."]
    elif sc.goal == "compare":
        c = q.compare(catalog, sc.scope, sc.target, sc.compare_by, sc.compare_groups)
        if not c or len(c["groups"]) < 2:
            return None
        what = q.TARGET_TEXT[sc.target]
        head = [f"{g['group']}: the flame {what} in {g['hits']} of {g['n']} tests ({_pct(g['share'])}, 95% range {_pct(g['low'])} to {_pct(g['high'])})." for g in c["groups"]]
        head.append("These are counts of what was tested. The tests did not change one gas at a time, so the groups also differ in oxygen, pressure and fuel.")
        metrics = [{"label": g["group"], "value": f"{g['hits']}/{g['n']}"} for g in c["groups"]]
        rows = [r for g in c["groups"] for r in [x for x in q.select(catalog, sc.scope) if x["outcome"] and (x["diluent"] if c["by"] == "diluent" else x["fuel_key"] if c["by"] == "fuel" else x["name"]) == g["group"]][:6]]
        title = f"How {', '.join(g['group'] for g in c['groups'])} compare: the flame {what}"
        extra = ["Oxygen ranges tested per group: " + "; ".join(f"{g['group']} {g['o2'][0] * 100:.0f} to {g['o2'][1] * 100:.0f}%" for g in c["groups"]) + "."]
    elif sc.goal == "profile":
        pr = q.profile(catalog, sc.scope, sc.target, sc.variable)
        if not pr or len(pr["bands"]) < 2:
            return None
        what, unit = q.TARGET_TEXT[sc.target], ("oxygen", "%", 100) if sc.variable == "o2" else ("pressure", " atm", 1)
        solid = [b for b in pr["bands"] if b["n"] >= 5] or pr["bands"]
        a, z = solid[0], solid[-1]
        band = lambda b: f"{b['low_edge'] * unit[2]:g} to {b['high_edge'] * unit[2]:g}{unit[1]}"   # noqa: E731
        head = [f"Across {pr['n']} tests ({sc.scope.text()}), the flame {what} in {pr['hits']} ({_pct(pr['hits'] / pr['n'])}).",
                f"At {unit[0]} {band(a)} it {what} in {a['hits']} of {a['n']} tests ({_pct(a['share'])}); at {band(z)} in {z['hits']} of {z['n']} ({_pct(z['share'])})."]
        metrics = [{"label": f"{unit[0]} {band(b)}", "value": f"{b['hits']}/{b['n']}"} for b in pr["bands"]][:6]
        rows = pr["rows"]
        title, extra = f"How the share that {what} changes with {unit[0]}: {sc.scope.text()}", ["Bands are fixed widths. Tests also differ in fuel, gas and pressure, so a trend across bands is not a controlled comparison."]
        card_table = {"columns": [f"{unit[0].capitalize()} band", "Tests", what.capitalize(), "Share", "95% range"],
                      "rows": [[band(b), str(b["n"]), str(b["hits"]), _pct(b["share"]), f"{_pct(b['low'])} to {_pct(b['high'])}"] for b in pr["bands"]], "shown": len(pr["bands"]), "total": len(pr["bands"]), "psi": []}
    else:
        o = q.outcomes(catalog, sc.scope)
        if not o["n"]:
            return None
        top = o["counts"].most_common(4)
        head = [f"Of {o['n']} tests ({sc.scope.text()}) from {_names(o['rows'])}: " + "; ".join(f"{q.OUTCOME_TEXT.get(k, k)} in {v} ({_pct(v / o['n'])})" for k, v in top) + "."]
        metrics = [{"label": q.OUTCOME_TEXT.get(k, k), "value": str(v)} for k, v in top]
        rows, title, extra = o["rows"], f"What happened: {sc.scope.text()}", []
        fuels = q.by_fuel(o["rows"], sc.target)
        if len(fuels) > 1:
            head.append("By fuel or material: " + "; ".join(f"{f['fuel']} {f['n']} test{'s' if f['n'] != 1 else ''}" + (f" ({f['hits']} {q.TARGET_TEXT[sc.target]})" if sc.target else "") for f in fuels[:6]) + ".")
        lo_, hi_ = min(r["o2"] for r in o["rows"]), max(r["o2"] for r in o["rows"])
        head.append(f"Oxygen in these tests ran from {lo_ * 100:.0f}% to {hi_ * 100:.0f}%.")
        if re.search(r"\b(elevated|enriched|oxygen-rich|high(?:er)? oxygen|more oxygen)\b", sc.asked, re.I) and hi_ <= 0.25:
            head.append(f"None of these tests used more than {hi_ * 100:.0f}% oxygen, so they do not cover elevated oxygen.")
    return {"goal": sc.goal, "title": title, "scope": sc.scope.text(), "headline": head, "metrics": metrics, "table": card_table if sc.goal == "profile" else q.table(rows),
            "caveats": _caveats(catalog, extra, rows), "links": [x for x in [_link(rows, sc.scope)] if x]}


def no_match(catalog: Catalog, sc: Scenario) -> dict:
    """Nothing matches every condition: say which condition removes the tests, and what does exist without it."""
    base = sc.scope
    pieces = [("fuel or material", "fuel"), ("gas mixed with oxygen", "diluent"), ("oxygen range", "o2"), ("pressure range", "p_psi"), ("investigation", "psi_ids")]
    head = [f"No mapped PSI test matches all of: {base.text()}."]
    rows: list[dict] = []
    for label, attr in pieces:
        if not getattr(base, attr):
            continue
        relaxed = q.Scope(**{**base.__dict__, attr: None if attr != "psi_ids" else []})
        found = q.select(catalog, relaxed)
        if found:
            head.append(f"Without the {label} condition, {len(found)} tests match ({_names(found)}; oxygen {min(r['o2'] for r in found) * 100:.0f} to {max(r['o2'] for r in found) * 100:.0f}%, "
                        f"pressure {min(r['p_psi'] for r in found):.1f} to {max(r['p_psi'] for r in found):.1f} psi).")
            rows = rows or found
    if len(head) == 1:
        head.append("None of the 1,411 mapped tests relate to those words. Only some investigations have tests with oxygen and pressure mapped; the rest can only be searched as documents.")
    return {"goal": "none", "title": f"No test matches: {base.text()}", "scope": base.text(), "headline": head, "metrics": [], "table": q.table(rows) if rows else None,
            "caveats": _caveats(catalog, ["A missing match is not proof that nothing was tested: tables that are not mapped cannot be searched this way."], rows), "links": []}


# ------------------------------------------------------------------ conversation: the conditions to remember, and what to suggest next
def slots(sc: Scenario) -> dict | None:
    """The scenario as the form's fields, so the next question can build on it. None when it cannot be written that way."""
    if sc.compare_by in ("fuel", "investigation"):
        return None
    o2 = sc.o2_point if sc.o2_point is not None else (sum(sc.scope.o2) / 2 if sc.scope.o2 and None not in sc.scope.o2 else None)
    p = sc.p_point_psi if sc.p_point_psi is not None else (sum(sc.scope.p_psi) / 2 if sc.scope.p_psi and None not in sc.scope.p_psi else None)
    return {"goal": sc.goal, "target": sc.target, "variable": sc.variable if sc.goal in ("threshold", "profile") else None, "fuel": sc.scope.fuel, "diluent": sc.scope.diluent,
            "o2": o2, "p_psi": p}


def context_note(sc: Scenario) -> str | None:
    if not sc.inherited and not sc.changed:
        return None
    kept = ", ".join(sc.inherited)
    return "Following on from your last question" + (f" (keeping the {kept})" if kept else "") + (f"; you changed the {', '.join(sc.changed)}." if sc.changed else ".")


def suggest(catalog: Catalog, sc: Scenario, limit: int = 3) -> list[str]:
    """Follow-up questions that will really be answered: each is tried before it is offered."""
    cands: list[str] = []
    target = sc.target or ("extinguish" if sc.scope.kind == "end_state" else "burn")
    pool = q.select(catalog, q.Scope(kind=sc.scope.kind, with_outcome=True, psi_ids=list(sc.scope.psi_ids)))
    fuels = [f for f, _ in __import__("collections").Counter(r["fuel_key"] for r in pool if r["fuel_key"] and q.positive(r, target) is not None).most_common(4) if f != sc.scope.fuel]
    if sc.goal in ("threshold", "outcomes", "profile"):
        cands += [f"What about {f}?" for f in fuels[:2]]
    if sc.goal in ("threshold", "outcomes", "profile") and not sc.scope.diluent and sc.scope.kind in (None, "end_state"):
        cands.append("How do helium and carbon dioxide compare?")
    if sc.goal == "nearest":
        cands += ["What happened in those tests?"]
    if sc.goal == "compare" and sc.scope.fuel is None:
        cands += ["What about methanol?", "What about heptane?"]
    out = []
    for text in cands:
        sc2 = read(text, _FrameLike(), None, slots(sc))
        if sc2 and (analyse(catalog, sc2) is not None) and text not in out:
            out.append(text)
    return out[:limit]


class _FrameLike:
    """Just enough of a question reading for suggest() to test a follow-up: no investigation named, no oxygen or pressure."""
    o2 = None
    pressure = None
    psi_ids: list = []
    question = ""
