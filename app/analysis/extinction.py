"""Experiment vs simulation: figure data from PSI-117 (n-dodecane droplets), read from the stored Analyzed Data files. No SI.

Each series is labelled as measured ("experiment"), computed ("simulation") or "bounds" exactly as the file's own column names say.
Nothing here enters a test count, a skill check or a pattern: these are the investigators' figure data, drawn as they are.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from app.analysis.sweeper import ATM_PSI, _value
from app.catalog import Catalog

PSI_ID = "PSI-117"
EXTINCTION = "PSI-117_Analyzed Data_PROCI_2023_C12_Extinction_Diameter_vs_pressure.csv"
KAVG = "PSI-117_Analyzed Data_MST_2024_Kavg.csv"


def _number(text: str) -> float | None:
    try:
        return float(text.strip())
    except ValueError:
        return None


def _rows(path: Path) -> list[list[str]]:
    return list(csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig", errors="replace"))))


def _pairs(rows: list[list[str]], x_col: int, y_col: int) -> list[list[float]]:
    out = []
    for r in rows[1:]:
        x, y = (_number(r[x_col]) if x_col < len(r) else None), (_number(r[y_col]) if y_col < len(r) else None)
        if x is not None and y is not None:
            out.append([x, y])
    return out


def _kind(name: str) -> str:
    n = name.lower()
    if "error" in n:
        return "bounds"
    return "simulation" if re.search(r"model|sim", n) else "experiment"


def extinction_chart(snapshot: Path) -> dict | None:
    """Fig. 7: extinction diameter against pressure, hot and cool flames, experiment and model, from the file's own column blocks."""
    path = snapshot / "analyzed" / PSI_ID / EXTINCTION
    if not path.exists():
        return None
    rows = _rows(path)
    header, series = rows[0], []
    for i, name in enumerate(header):
        if name.strip().lower().startswith("dext") and i > 0 and header[i - 1].strip().lower().startswith("p ("):
            label = name.strip()
            flame = "cool flame" if "_CF" in label else "hot flame"
            series.append({"name": label, "flame": flame, "group": flame, "kind": _kind(label), "points": _pairs(rows, i - 1, i),
                           "bound": "upper" if label.endswith("+") else "lower" if label.endswith("-") else None})
    return {"figure": "Fig. 7", "file": EXTINCTION, "title": "Extinction diameter against pressure (n-dodecane droplet)",
            "x": {"label": "Pressure (atm)"}, "y": {"label": "Extinction diameter", "unit_note": "The file gives no unit; the list of data gives the droplet size in mm, so this is read on the same scale."},
            "series": series,
            "note": "Experiment is measured; Model is the investigators' computed result. ErrorBar+ and ErrorBar- are drawn as the upper and lower values of a bar, as written in the file."}


def burning_rate_chart(snapshot: Path) -> dict | None:
    """Fig. 4: burning-rate constant against pressure, experiment and model."""
    path = snapshot / "analyzed" / PSI_ID / KAVG
    if not path.exists():
        return None
    rows = _rows(path)
    return {"figure": "Fig. 4", "file": KAVG, "title": "Burning-rate constant against pressure (n-dodecane droplet)",
            "x": {"label": "Pressure (atm)"}, "y": {"label": "Burning-rate constant", "unit_note": "The model column is labelled mm²/s; the experiment column carries no unit in the file."},
            "series": [{"name": "Kavg_CF (experiment)", "flame": "cool flame", "group": "cool flame", "kind": "experiment", "points": _pairs(rows, 1, 2), "bound": None},
                       {"name": "kb (model)", "flame": "cool flame", "group": "cool flame", "kind": "simulation", "points": _pairs(rows, 5, 6), "bound": None}],
            "note": "The file names the experiment column Kavg_CF and the model column kb (mm2/s)."}


# The tests of another investigation (CFI, PSI-39) that match this figure's conditions. Shown only when asked, apart from the figure's own series.
OVERLAY = {"fuel": "C12H26", "o2": (0.205, 0.215), "droplet_mm": (3.5, 4.5), "p_atm": (0.5, 3.05)}


def cfi_overlay(catalog: Catalog) -> dict:
    """CFI (PSI-39) measured extinction diameters for pure n-dodecane in air at the figure's pressures and droplet size."""
    hot, cool, used = [], [], 0
    for t in catalog.tests:
        if t["investigation"] != "PSI-39" or _value(t, "fuel") != OVERLAY["fuel"]:
            continue
        o2, p, d0 = _value(t, "o2_fraction"), _value(t, "pressure_psi"), _value(t, "droplet_diameter_mm")
        if None in (o2, p, d0) or not (OVERLAY["o2"][0] <= o2 <= OVERLAY["o2"][1] and OVERLAY["droplet_mm"][0] <= d0 <= OVERLAY["droplet_mm"][1]):
            continue
        atm = p / ATM_PSI
        if not OVERLAY["p_atm"][0] <= atm <= OVERLAY["p_atm"][1] or (_value(t, "he_fraction") or 0) > 0:
            continue
        label = f"CFI test {t['test_id']}: droplet {d0:g} mm, row {t['row']}"
        h, c = _value(t, "extinction_diameter_mm"), _value(t, "cool_extinction_diameter_mm")
        used += 1
        if h is not None:
            hot.append([round(atm, 3), h, label])
        if c is not None:
            cool.append([round(atm, 3), c, label])
    return {"conditions": "pure n-dodecane (C12H26), 21% oxygen in nitrogen only, initial droplet 3.5 to 4.5 mm, 0.5 to 3 atm", "tests": used,
            "source": "ACME CFI (PSI-39) measured tests",
            "series": [{"name": "CFI measured, hot flame", "kind": "experiment-cfi", "group": "hot flame", "points": hot, "bound": None},
                       {"name": "CFI measured, cool flame", "kind": "experiment-cfi", "group": "cool flame", "points": cool, "bound": None}]}


INTRO = {"PSI-117": "Figure data published by the PSI-117 investigators. Measured results and the investigators' own simulation are drawn apart and are never combined in any count, estimate or pattern.",
         "PSI-142": "Figure data from the PSI-142 workbook, one sheet per figure of the investigators' papers. The workbook does not label these series measured or computed, so they are drawn as published and never combined in any count, estimate or pattern."}


def investigation_figures(catalog: Catalog, snapshot: Path, psi_id: str) -> dict:
    """The figure data of any investigation that has stored Analyzed Data files and reviewed figure specs."""
    if psi_id == PSI_ID:
        return {**charts(catalog, snapshot), "intro": INTRO[PSI_ID]}
    from app.analysis import figures
    inv = catalog.get(psi_id)
    entry = catalog.manifest["investigations"].get(psi_id, {})
    extra = figures.charts_for(psi_id, snapshot)
    return {"psi": psi_id, "doi": (inv or {}).get("doi"), "license": (inv or {}).get("license"), "intro": INTRO.get(psi_id), "dropped": extra["dropped"],
            "charts": [{**c, "reference": None, "conditions": {}} for c in extra["charts"]],
            "files": [{"file": f["file"].rsplit("/", 1)[-1], "bytes": f["bytes"], "sha256": f["sha256"], "figure": f.get("figure")} for f in entry.get("analyzed", [])]}


def charts(catalog: Catalog, snapshot: Path) -> dict:
    inv = catalog.get(PSI_ID)
    refs = {r.get("Data File"): r for r in ((inv or {}).get("simulated_data") or {}).get("rows", [])}
    out = []
    from app.analysis import figures
    extra = figures.charts_for(PSI_ID, snapshot)
    base = [c for c in (extinction_chart(snapshot), burning_rate_chart(snapshot)) if c]
    for c in base:
        if c["figure"] == "Fig. 7":
            c["overlay"] = cfi_overlay(catalog)
    for c in [*base, *extra["charts"]]:
        ref = refs.get(c["file"].replace("PSI-117_Analyzed Data_", "").replace(".csv", ""), {})
        out.append({**c, "reference": (ref.get("Reference") or "").strip() or None, "conditions": {k: ref.get(k) for k in ("Fuel", "do (mm)", "P (atm)", "XO2", "XN2") if ref.get(k)}})
    entry = catalog.manifest["investigations"].get(PSI_ID, {})
    return {"psi": PSI_ID, "doi": (inv or {}).get("doi"), "license": (inv or {}).get("license"), "charts": out, "dropped": extra["dropped"],
            "files": [{"file": f["file"].rsplit("/", 1)[-1], "bytes": f["bytes"], "sha256": f["sha256"], "figure": f.get("figure")} for f in entry.get("analyzed", [])]}
