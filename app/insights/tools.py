"""The tools SI Insights can use. Every tool is read-only and deterministic: it returns evidence items.

The Investigator (SI) chooses which tools to call and with what arguments, but every argument is
checked here (investigation IDs must exist, sections and filters come from fixed lists), and every
fact in a result comes from the PSI snapshot. Counts and comparisons are computed by code.

An item with an id starting "C:" is computed by code from the snapshot on the spot.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path

from app.analysis import compare as compare_mod
from app.insights.library import Item, Library

SECTIONS = {"objective": "objective", "approach": "approach", "hypothesis": "hypothesis",
            "benefits": "impacts", "description": "description", "hardware": "hardware_text"}
TYPES = ("Microgravity", "Ground")
MAX_QUERY = 200
TOOL_MENU = {
    "search_library": "Search record text, publications, tags and file lists. Args: query, optional psi_ids.",
    "search_documents": "Search the text of PSI's reports, science documents and ReadMe files. Args: query, optional psi_ids.",
    "get_investigation": "Record facts, tags, method label, related investigations and test summary of one investigation. Args: psi_ids.",
    "get_section": "One section of the record (objective, approach, hypothesis, benefits, description, hardware). Args: psi_ids, section.",
    "get_method": "Whether the work was experimental or simulation, with its checked evidence sentence. Args: psi_ids.",
    "get_lineage": "Which flight investigation a ground study uses, and which studies use its data. Args: psi_ids.",
    "get_test_stats": "Test counts, ranges, fuels and outcomes, or the test table's columns. Args: psi_ids.",
    "find_tests": "Find test rows by words, fuel, oxygen or pressure. Args: optional query, psi_ids, fuel, o2_min, o2_max, pressure_min, pressure_max.",
    "get_publications": "The publications of one investigation. Args: psi_ids, optional query.",
    "list_files": "The files PSI holds for an investigation and which documents were read. Args: psi_ids.",
    "compare": "Compare two to four investigations attribute by attribute. Args: psi_ids.",
    "count_investigations": "Count and list investigations by type, method, fuel class or topic word. Args: optional type, method, fuel_class, query.",
}


class ToolError(ValueError):
    pass


@dataclass
class ToolCall:
    tool: str
    psi_ids: list[str]
    query: str = ""
    section: str | None = None
    type: str | None = None
    method: str | None = None
    fuel_class: str | None = None
    fuel: str | None = None
    o2_min: float | None = None
    o2_max: float | None = None
    pressure_min: float | None = None
    pressure_max: float | None = None
    reuses_flight_data: bool = False      # count only investigations that PSI lists as building on another investigation's flight data

    def label(self) -> str:
        bits = [self.tool] + ([",".join(self.psi_ids)] if self.psi_ids else []) + ([f'"{self.query}"'] if self.query else [])
        return " ".join(bits)


def computed(key: str, text: str, psi: str = "-") -> Item:
    return Item(f"C:{key}", "C", psi, text, "computed by code from the PSI snapshot")


class Toolbox:
    def __init__(self, library: Library) -> None:
        self.lib = library
        self.catalog = library.catalog
        self.ids = {i["id"] for i in self.catalog.ordered()}
        self._rows = {}
        for item in library.items.values():
            if item.kind == "T":
                self._rows[(item.file, item.row)] = item
        self._tables = _table_info(library)

    # ------------------------------------------------------------ validation
    def check(self, raw: dict) -> ToolCall:
        tool = raw.get("tool")
        if tool not in TOOL_MENU:
            raise ToolError(f"unknown tool {tool!r}")
        ids = [i for i in dict.fromkeys(raw.get("psi_ids") or []) if i in self.ids][:4]
        section = raw.get("section")
        section = section if section in SECTIONS else None
        num = lambda k: (float(raw[k]) if isinstance(raw.get(k), (int, float)) and not isinstance(raw.get(k), bool) else None)  # noqa: E731
        return ToolCall(tool=tool, psi_ids=ids, query=re.sub(r"\s+", " ", str(raw.get("query") or ""))[:MAX_QUERY].strip(),
                        section=section, type=raw.get("type") if raw.get("type") in TYPES else None,
                        method=raw.get("method") if raw.get("method") in ("experimental", "simulation") else None,
                        fuel_class=raw.get("fuel_class") if raw.get("fuel_class") in ("gas", "liquid", "solid") else None,
                        fuel=(str(raw["fuel"])[:40] if raw.get("fuel") else None),
                        o2_min=num("o2_min"), o2_max=num("o2_max"), pressure_min=num("pressure_min"), pressure_max=num("pressure_max"),
                        reuses_flight_data=raw.get("reuses_flight_data") is True)

    # ------------------------------------------------------------ running
    def run(self, call: ToolCall, limit: int = 6) -> list[Item]:
        handler = getattr(self, f"_{call.tool}")
        items = handler(call, limit)
        seen, out = set(), []
        for it in items:
            if it.id not in seen:
                seen.add(it.id)
                out.append(it)
        return out

    def _need(self, call: ToolCall) -> list[str]:
        if not call.psi_ids:
            raise ToolError(f"{call.tool} needs an investigation")
        return call.psi_ids

    def _search_library(self, c: ToolCall, limit: int) -> list[Item]:
        return self.lib.search(c.query, kinds="RIAMLSPF", psi_ids=c.psi_ids or None, limit=limit)

    def _search_documents(self, c: ToolCall, limit: int) -> list[Item]:
        return self.lib.search(c.query, kinds="D", psi_ids=c.psi_ids or None, limit=limit)

    def _get_investigation(self, c: ToolCall, limit: int) -> list[Item]:
        out = []
        for psi_id in self._need(c):
            out += [i for kind in "IAMLS" if (i := self.lib.get(f"{kind}:{psi_id}"))]
        return out

    def _get_section(self, c: ToolCall, limit: int) -> list[Item]:
        field = SECTIONS.get(c.section or "approach", "approach")
        out = []
        for psi_id in self._need(c):
            out += [i for i in self.lib.by_psi(psi_id, "R") if i.id.split(":")[2] == field][:limit]
        return out

    def _get_method(self, c: ToolCall, limit: int) -> list[Item]:
        return [i for psi_id in self._need(c) for i in (self.lib.get(f"M:{psi_id}"), self.lib.get(f"L:{psi_id}")) if i]

    def _get_lineage(self, c: ToolCall, limit: int) -> list[Item]:
        return [i for psi_id in self._need(c) if (i := self.lib.get(f"L:{psi_id}"))] or \
               [computed(f"lineage:{p}", f"PSI lists no flight-data link for {self.catalog.get(p)['name']}.", p) for p in c.psi_ids]

    def _get_test_stats(self, c: ToolCall, limit: int) -> list[Item]:
        out = []
        for psi_id in self._need(c):
            name = self.catalog.get(psi_id)["name"]
            if (s := self.lib.get(f"S:{psi_id}")):
                out.append(s)
            tables = self._tables.get(psi_id, [])
            if tables:
                lines = [f"{t['file']}: {t['rows']} rows; columns: {', '.join(t['columns'])}" for t in tables]
                out.append(computed(f"tables:{psi_id}", f"{name} has {len(tables)} test table(s) from PSI. " + " | ".join(lines)
                                    + ("" if s else " Its values are available only as raw rows (search them with find_tests); "
                                       "its columns haven't been mapped to units yet, so no ranges are computed."), psi_id))
            elif not s:
                out.append(computed(f"tables:{psi_id}", f"PSI lists no test table for {name}.", psi_id))
        return out

    def _find_tests(self, c: ToolCall, limit: int) -> list[Item]:
        ids = c.psi_ids or None
        numeric = any(v is not None for v in (c.o2_min, c.o2_max, c.pressure_min, c.pressure_max)) or c.fuel
        out: list[Item] = []
        if numeric:
            hits = self._filter_mapped(c)
            fuels = f" fuel {c.fuel}" if c.fuel else ""
            rng = " and ".join(x for x in (
                f"oxygen {_span(c.o2_min, c.o2_max, 100, '%')}" if c.o2_min is not None or c.o2_max is not None else "",
                f"pressure {_span(c.pressure_min, c.pressure_max, 1, ' psi')}" if c.pressure_min is not None or c.pressure_max is not None else "") if x)
            unmapped = [i["name"] for i in self.catalog.ordered() if i["is_combustion"] and not i["stats"] and self._tables.get(i["id"])]
            text = (f"Searched the {len(self.catalog.tests)} test(s) whose columns are mapped (only {', '.join(sorted({t['investigation'] for t in self.catalog.tests}))})"
                    f" for{fuels} {rng}: {len(hits)} match. "
                    f"{len(unmapped)} other investigations have test tables whose columns aren't mapped yet, so numeric filters can't see them; "
                    "that does not mean those investigations never tested these conditions.")
            out.append(computed("find_tests:" + re.sub(r"\W+", "_", rng + fuels), text, hits[0]["investigation"] if hits else "-"))
            for t in hits[: max(0, limit - 1)]:
                if (row := self._rows.get((t["file"], t["row"]))):
                    out.append(row)
        if c.query or not numeric:
            out += self.lib.search(c.query or c.fuel or "", kinds="T", psi_ids=ids, limit=limit)
        return out

    def _filter_mapped(self, c: ToolCall) -> list[dict]:
        def v(t, name):
            x = t["values"].get(name)
            return x["value"] if x and x["flag"] in ("ok", "approx", "range") else None
        hits = []
        for t in self.catalog.tests:
            if c.psi_ids and t["investigation"] not in c.psi_ids:
                continue
            if c.fuel and c.fuel.lower() not in str(v(t, "fuel") or "").lower():
                continue
            o2, p = v(t, "o2_fraction"), v(t, "pressure_psi")
            if (c.o2_min is not None and (o2 is None or o2 < c.o2_min)) or (c.o2_max is not None and (o2 is None or o2 > c.o2_max)):
                continue
            if (c.pressure_min is not None and (p is None or p < c.pressure_min)) or (c.pressure_max is not None and (p is None or p > c.pressure_max)):
                continue
            hits.append(t)
        return hits

    def _get_publications(self, c: ToolCall, limit: int) -> list[Item]:
        out = []
        for psi_id in self._need(c):
            if c.query:
                out += self.lib.search(c.query, kinds="P", psi_ids=[psi_id], limit=limit)
            else:
                out += self.lib.by_psi(psi_id, "P")[:limit]
            n = len(self.catalog.get(psi_id)["publications"])
            out.append(computed(f"pubcount:{psi_id}", f"PSI lists {n} publication(s) for {self.catalog.get(psi_id)['name']}.", psi_id))
        return out

    def _list_files(self, c: ToolCall, limit: int) -> list[Item]:
        return [i for psi_id in self._need(c) if (i := self.lib.get(f"F:{psi_id}"))]

    def _compare(self, c: ToolCall, limit: int) -> list[Item]:
        ids = self._need(c)
        if len(ids) < 2:
            raise ToolError("compare needs two to four investigations")
        result = compare_mod.compare(self.catalog, ids)
        names = {i["id"]: i["name"] for i in result["investigations"]}
        lines = []
        for row in result["attributes"]:
            cells = "; ".join(f"{names[i]}: {', '.join(v) if v else 'none found'}" for i, v in row["cells"].items())
            tag = "same for all" if row["all_same"] else "differs"
            lines.append(f"{row['attribute']} ({tag}): {cells}.")
        out = [computed("compare:" + "+".join(ids), "Comparison, computed by code from the records: " + " ".join(lines), ids[0])]
        out += [i for psi_id in ids if (i := self.lib.get(f"M:{psi_id}"))]
        return out

    def matching(self, c: ToolCall) -> list[dict]:
        """The investigations a count_investigations call matches (also used to show the list)."""
        rows = []
        for inv in self.catalog.ordered():
            if c.type and inv["project_type"] != c.type:
                continue
            m = inv["method"]
            if c.method and not (m["status"] in ("verified", "team-confirmed") and _has_method(m["flag"], c.method)):
                continue
            if c.fuel_class and c.fuel_class not in inv["attributes"]["fuel_classes"]:
                continue
            if c.reuses_flight_data and not inv["uses_data_from"]:
                continue
            if c.query and not self.lib.search(c.query, psi_ids=[inv["id"]], limit=1):
                continue
            rows.append(inv)
        return rows

    def _count_investigations(self, c: ToolCall, limit: int) -> list[Item]:
        rows = self.matching(c)
        what = " ".join(x for x in (c.type, c.method and f"checked-{c.method}", c.fuel_class and f"{c.fuel_class}-fuel", "investigations",
                                    c.reuses_flight_data and "that use another investigation's flight data",
                                    c.query and f'mentioning "{c.query}"') if x)
        listing = ", ".join(f"{i['name']} ({i['id']})" if i["name"] != i["id"] else i["id"] for i in rows)
        text = f"Counted by code over the 26 investigations in PSI's combustion search: {len(rows)} {what}" + (f": {listing}." if rows else ".")
        if c.method:
            unconfirmed = [i["id"] for i in self.catalog.ordered() if i["method"]["status"] not in ("verified", "team-confirmed")]
            text += f" Only investigations whose method label was checked are counted; {len(unconfirmed)} are not confirmed yet ({', '.join(unconfirmed)})."
        return [computed("count:" + re.sub(r"\W+", "_", what), text)]


def _has_method(flag: str, wanted: str) -> bool:
    """`both` carries the two separate labels, Experimental and Simulation."""
    return flag == wanted or flag == "both"


def _span(lo: float | None, hi: float | None, scale: float, unit: str) -> str:
    f = lambda v: f"{v * scale:g}{unit}"  # noqa: E731
    if lo is not None and hi is not None:
        return f"{f(lo)} to {f(hi)}"
    return f"at least {f(lo)}" if lo is not None else f"at most {f(hi)}"


def _table_info(library: Library) -> dict[str, list[dict]]:
    """Row counts and column names of every downloaded test table, read from the snapshot."""
    out: dict[str, list[dict]] = {}
    data_dir = library.data_dir
    for psi_id, entry in library.catalog.manifest["investigations"].items():
        for table in entry["tables"]:
            text = (data_dir / "snapshot" / table["file"]).read_bytes().decode("utf-8-sig", errors="replace")
            reader = csv.reader(io.StringIO(text))
            header = [h.strip() for h in next(reader, []) if h.strip()]
            rows = sum(1 for r in reader if any(c.strip() for c in r))
            out.setdefault(psi_id, []).append({"file": Path(table["file"]).name, "rows": rows, "columns": header})
    return out


