"""Figure data from the stored PSI Analyzed Data files, drawn from reviewed specs (data/figures.yaml). No SI.

Each series names the file's own columns. The header text at those columns is checked when the file is read: a mismatch, or an x column
that is not in order where it should be, drops that series and says why. Nothing is guessed, converted or pooled with any test count.
"""

from __future__ import annotations

import csv
import io
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import ROOT
from app.psi import documents

SPECS = ROOT / "data" / "figures.yaml"
MAX_POINTS = 400


@lru_cache
def load_specs(path: Path = SPECS) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _num(text) -> float | None:
    try:
        return float(str(text).strip())
    except ValueError:
        return None


def _thin(points: list[list[float]]) -> list[list[float]]:
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / MAX_POINTS
    return [points[int(i * step)] for i in range(MAX_POINTS)] + [points[-1]]


class _Source:
    """One stored file as a grid of text: {row number (1-based): {column (0-based): text}}."""

    def __init__(self, path: Path) -> None:
        self.path, self._sheets = path, None
        if path.suffix.lower() == ".csv":
            rows = csv.reader(io.StringIO(path.read_bytes().decode("utf-8-sig", errors="replace")))
            self.csv = {n: {c: v for c, v in enumerate(r) if v.strip()} for n, r in enumerate(rows, 1)}
        else:
            self.csv = None

    def grid(self, sheet: str | None) -> dict[int, dict[int, str]]:
        if self.csv is not None:
            return self.csv
        if self._sheets is None:
            self._sheets = {name.strip().lower(): g for name, g in documents.read_sheets(self.path.read_bytes())}
        return self._sheets[(sheet or "").strip().lower()]


def _series(src: _Source, s: dict, header_row: int = 1) -> tuple[dict | None, str | None]:
    grid = src.grid(s.get("sheet"))
    head = grid.get(s.get("header_row", header_row), {})
    for col, want in (s.get("expect") or {}).items():
        have = head.get(int(col), "").strip().lower()
        if not have.startswith(str(want).strip().lower()):
            return None, f"{s['name']}: the header at column {int(col) + 1} is {head.get(int(col), '')!r}, not {want!r}"
    pts = []
    for n in sorted(r for r in grid if r > s.get("header_row", header_row)):
        x, y = _num(grid[n].get(s["x"], "")), _num(grid[n].get(s["y"], ""))
        if x is not None and y is not None:
            pts.append([x, y])
    if not pts:
        return None, f"{s['name']}: no numbers under those columns"
    breaks = sum(1 for a, b in zip(pts, pts[1:]) if b[0] < a[0])
    if s.get("monotonic") and breaks > max(1, 0.005 * len(pts)):                 # a stray point is tolerated; a column of another quantity is not
        return None, f"{s['name']}: the values under the x header are not in order, so the header and values disagree; not drawn"
    return {"name": s["name"], "kind": s["kind"], "group": s.get("group") or s["name"], "style": s.get("style"), "points": _thin(pts), "bound": None}, None


def charts_for(psi_id: str, snapshot: Path, specs: dict | None = None) -> dict:
    """{"charts": [...], "dropped": [reasons]} for one investigation, from its stored files."""
    out, dropped = [], []
    for f in (specs or load_specs()).get(psi_id, []):
        path = snapshot / "analyzed" / psi_id / f["file"]
        if not path.exists():
            dropped.append(f"{f['file']}: not stored in this snapshot")
            continue
        try:
            src = _Source(path)
            for c in f["charts"]:
                series = []
                for s in c["series"]:
                    one, why = _series(src, s)
                    if one:
                        series.append(one)
                    elif why:
                        dropped.append(why)
                if series:
                    out.append({"figure": f["figure"], "file": f["file"], "title": c["title"], "x": {"label": c["x"]}, "y": {"label": c["y"], "unit_note": c.get("unit_note")},
                                "series": series, "note": c.get("note"), "source": "figure data"})
        except (KeyError, ValueError) as e:
            dropped.append(f"{f['file']}: could not be read ({e})")
    return {"charts": out, "dropped": dropped}
