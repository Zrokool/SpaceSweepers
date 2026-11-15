"""The PSI library: every fact SI Insights can use, as numbered evidence items with a search index.

Everything comes from the committed PSI snapshot (via the catalog); nothing is fetched at run time.
Each item has a stable ID, the text, and where it came from, so an answer can cite it and a reader
can open the exact passage.

    R:PSI-69:approach:2     a passage of a record field (objective, approach, hypothesis, benefits…)
    I:PSI-69                the record's facts: title, type, platform, dates, DOI, license, sponsor, version
    A:PSI-69                fuels, hardware, sensors, fire-safety pillars (with their evidence) and equipment found in the record
    M:PSI-69                the Experimental / Simulation label, only as far as it was checked
    L:PSI-69                which flight investigation a ground study uses (and who uses its data)
    S:PSI-159               a summary of the parsed test table (counts, ranges, fuels, outcomes)
    T:PSI-25:3:row5         one row of a test table, as text
    D:PSI-10:d2:p12:1       a passage of a document (report, science document, ReadMe), with its page
    P:PSI-69:7              a publication: title, authors, DOI
    F:PSI-23                the files PSI holds, and which documents were read

Search is SQLite full-text search (BM25 ranking), held in memory.
"""

from __future__ import annotations

import csv
import io
import re
import sqlite3
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from app.analysis import pillars as pillar_mod
from app.catalog import Catalog, get_catalog

PASSAGE_CHARS = 700          # record passages and document chunks are grouped up to about this size
ROW_CHARS = 700
KIND_LABEL = {"V": "simulated data list", "R": "record", "I": "record facts", "A": "tags", "M": "method label", "L": "related investigations",
              "S": "test summary", "T": "test row", "D": "document", "P": "publication", "F": "file list",
              "C": "computed by code"}
FIELD_LABEL = {"objective": "Objective", "approach": "Approach", "hypothesis": "Hypothesis", "impacts": "Earth and space benefits",
               "description": "Description", "hardware_text": "Hardware", "proposal_title": "Proposal title",
               "acknowledgments": "Acknowledgments"}
METHOD_WORDS = {"experimental": "Experimental (the investigators ran their own physical tests)",
                "simulation": "Simulation (the investigators ran their own computer model or simulation)",
                "both": "Experimental and Simulation (two separate labels, each with its own evidence)"}
STOPWORDS = frozenset("""a an and are as at be been by can did do does for from had has have how i if in into is it its of on or
that the their them there these they this to was were what when where which who whom why will with would about across after
all also any between both each more most other over than then those through under up use used using very which while show tell
give list find many much per psi investigation investigations test tests recorded record measured measure data""".split())
SECTION = re.compile(r"\[\[(?:page (\d+)|sheet ([^\]]*?))\]\]")


@dataclass(frozen=True)
class Item:
    id: str
    kind: str
    psi: str
    text: str
    where: str                      # a human locator: "Approach", "test table BASS-II.csv, row 5", "SRD.pdf, page 12"
    file: str | None = None
    page: str | None = None         # a page number or sheet name
    row: int | None = None


@dataclass
class Library:
    items: dict[str, Item]
    catalog: Catalog
    unread: list[dict] = field(default_factory=list)     # documents listed but not read, with the reason
    data_dir: Path | None = None
    _db: sqlite3.Connection | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ---------- lookup ----------
    def get(self, item_id: str) -> Item | None:
        return self.items.get(item_id)

    def by_psi(self, psi_id: str, kinds: str | None = None) -> list[Item]:
        return [i for i in self.items.values() if i.psi == psi_id and (kinds is None or i.kind in kinds)]

    def source(self, item: Item) -> dict:
        """How an item is shown in a Sources list."""
        inv = self.catalog.get(item.psi)
        return {"id": item.id, "kind": item.kind, "kind_label": KIND_LABEL[item.kind], "psi": item.psi,
                "name": inv["name"] if inv else item.psi, "where": item.where, "file": item.file, "page": item.page,
                "row": item.row, "doi": inv["doi"] if inv else None, "url": inv["landing_url"] if inv else None}

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for i in self.items.values():
            out[i.kind] = out.get(i.kind, 0) + 1
        return out

    # ---------- search ----------
    def search(self, query: str, *, kinds: str | None = None, psi_ids: list[str] | None = None, limit: int = 8) -> list[Item]:
        match = fts_query(query)
        if not match or self._db is None:
            return []
        sql = "SELECT id FROM items WHERE items MATCH ?"
        args: list = [match]
        if kinds:
            sql += f" AND kind IN ({','.join('?' * len(kinds))})"
            args += list(kinds)
        if psi_ids:
            sql += f" AND psi IN ({','.join('?' * len(psi_ids))})"
            args += list(psi_ids)
        sql += " ORDER BY bm25(items, 0, 0, 0, 0.6, 1.0) LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self._db.execute(sql, args).fetchall()
        return [self.items[r[0]] for r in rows if r[0] in self.items]


# Words a question uses vs how PSI's tables write them (columns say "CO (ppm)", "XO2", "p (atm)").
SYNONYMS = {
    r"carbon monoxide": ["co"], r"carbon dioxide": ["co2"], r"\boxygen\b": ["o2", "xo2"], r"\bpressure\b": ["atm", "psi", "bar"],
    r"\btemperature\b": ["temp"], r"\bairflow\b|\bair flow\b|\bventilation\b": ["flow", "velocity"],
    r"\bsmoke\b": ["aerosol", "particle"], r"\bburning rate\b|\bburn rate\b": ["burn", "rate"],
}


def fts_query(text: str) -> str:
    """A safe full-text query: plain words only, stopwords dropped, synonyms added, joined with OR."""
    text = text or ""
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", text)]
    for pattern, extra in SYNONYMS.items():
        if re.search(pattern, text, re.I):
            words += extra
    words = [w for w in dict.fromkeys(words) if len(w) > 1 and w not in STOPWORDS]
    return " OR ".join(f'"{w}"' for w in words[:24])


# ---------------------------------------------------------------- building items
def passages(text: str, limit: int = PASSAGE_CHARS) -> list[str]:
    """Split text into passages of about `limit` characters on sentence and line boundaries. Nothing is dropped."""
    units = [u.strip() for u in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9(\"“])|\n+", text or "") if u.strip()]
    out, current = [], ""
    for unit in units:
        if current and len(current) + len(unit) + 1 > limit:
            out.append(current)
            current = ""
        current = f"{current} {unit}".strip()
        while len(current) > limit * 2:                 # a very long unbroken line is cut at a space
            cut = current.rfind(" ", 0, limit * 2) or limit * 2
            out.append(current[:cut].strip())
            current = current[cut:].strip()
    if current:
        out.append(current)
    return out


def doc_short(file_name: str, psi_id: str) -> str:
    return re.sub(r"\.(pdf|docx|xlsx|txt|csv)$", "", file_name.replace(f"{psi_id}_", "", 1), flags=re.I)


def _range_text(r: list[float] | None, digits: int, unit: str) -> str:
    if not r:
        return "no values"
    fmt = lambda v: f"{v:.{digits}f}".rstrip("0").rstrip(".") if digits else f"{v:.0f}"  # noqa: E731
    return f"{fmt(r[0])} {unit}" if r[0] == r[1] else f"{fmt(r[0])} to {fmt(r[1])} {unit}"


def _record_items(inv: dict) -> list[Item]:
    out = []
    for fld, label in FIELD_LABEL.items():
        text = (inv.get(fld) or "").strip()
        for n, p in enumerate(passages(text), 1):
            out.append(Item(f"R:{inv['id']}:{fld}:{n}", "R", inv["id"], p, label))
    if inv["keywords"]:
        out.append(Item(f"R:{inv['id']}:keywords:1", "R", inv["id"], "Keywords: " + "; ".join(inv["keywords"]), "Keywords"))
    return out


def _facts_item(inv: dict) -> Item:
    bits = [f"{inv['name']} ({inv['id']}): {inv['title']}.",
            f"PSI project type: {inv['project_type']} investigation." + (f" Platform: {inv['platform']}." if inv["platform"] else ""),
            f"PSI research area: {inv['research_area']}" + (f", topic: {inv['sub_area']}." if inv["sub_area"] else "."),
            f"DOI: {inv['doi']}." if inv["doi"] else "PSI records no DOI for it.",
            f"License: {inv['license']}." if inv["license"] else "PSI records no license for it."]
    if inv["proposal_title"]:
        bits.append(f"Proposal title: {inv['proposal_title']}.")
    if inv["sponsor"]:
        bits.append(f"Sponsor: {inv['sponsor']}.")
    if inv["nasa_center"]:
        bits.append(f"NASA center: {inv['nasa_center']}.")
    if inv["start_date"] or inv["end_date"]:
        bits.append(f"Dates: {inv['start_date'] or '?'} to {inv['end_date'] or '?'}.")
    if inv["version"]:
        bits.append(f"PSI version {inv['version']}" + (f" ({inv['version_reason']})" if inv["version_reason"] not in (None, "None") else "")
                    + (f", released {inv['release_date']}" if inv["release_date"] else "") + ".")
    if inv["hardware_text"]:
        bits.append(f"Hardware: {inv['hardware_text']}.")
    if not inv["is_combustion"]:
        bits.append(f"It is not combustion research ({inv['research_area']}); it is in PSI's combustion search because it {inv['match_reason']}.")
    return Item(f"I:{inv['id']}", "I", inv["id"], " ".join(bits), "Record details")


def _tags_item(inv: dict) -> Item | None:
    a = inv["attributes"]
    parts = []
    if a["fuels"]:
        parts.append("Fuels named: " + ", ".join(sorted({f"{f['term']} ({f['fuel_class']})" for f in a["fuels"]})))
    if a["hardware"]:
        parts.append("Hardware: " + ", ".join(h["label"] for h in a["hardware"]))
    if a["sensors"]:
        parts.append("Sensors and measurements: " + ", ".join(s["label"] for s in a["sensors"]))
    informed = [f"{p} ({pillar_mod.describe(v)})" for p, v in inv["pillars"].items() if v["status"] in ("evidence", "data only")]
    if informed:
        parts.append("Fire-safety pillars the research informs, with evidence: " + "; ".join(informed))
    if a["equipment"]:
        parts.append("Equipment and controls its text says it informs: " + ", ".join(e["label"] for e in a["equipment"]))
    if a["solid_emulation"]:
        parts.append("It emulates burning solids with a gas burner.")
    if not parts:
        return None
    return Item(f"A:{inv['id']}", "A", inv["id"], f"{inv['name']}: " + ". ".join(parts) + ".", "Tags found in the record text")


def _method_item(inv: dict) -> Item:
    m = inv["method"]
    if m.get("status") in ("verified", "team-confirmed") and m.get("flag") in METHOD_WORDS:
        text = f"{inv['name']} method label (checked by rules): {METHOD_WORDS[m['flag']]}."
        for kind in ("experimental", "simulation"):
            part = m.get(kind)
            if part and part.get("quote"):
                text += f' {kind.capitalize()} evidence, from its {part.get("field") or "record"}: "{part["quote"]}"'
            elif part:
                text += f" {kind.capitalize()}: {part['basis']}"
        if m.get("review"):
            text += " Not decided: " + " ".join(m["review"])
    else:
        text = f"{inv['name']}: not classified (whether it was experimental or a simulation is not confirmed). " + (m.get("reason") or "")
    return Item(f"M:{inv['id']}", "M", inv["id"], text.strip(), "Method label")


def _lineage_item(inv: dict, names: dict[str, str]) -> Item | None:
    def label(psi_id: str) -> str:
        if psi_id not in names:
            return f"{psi_id} (not one of the 26 investigations in this dashboard)"
        name = names[psi_id]
        return psi_id if name == psi_id else f"{name} ({psi_id})"

    bits = []
    if inv["uses_data_from"]:
        bits.append(f"{inv['name']} is a {inv['project_type']} investigation that uses flight data from "
                    + ", ".join(label(i) for i in inv["uses_data_from"]) + ".")
    if inv["data_used_by"]:
        bits.append(f"{inv['name']}'s data is used by " + ", ".join(label(i) for i in inv["data_used_by"]) + ".")
    other = [i for i in inv["related"] if i not in inv["uses_data_from"]]
    if other:
        bits.append("PSI also lists as related: " + ", ".join(label(i) for i in other) + ".")
    return Item(f"L:{inv['id']}", "L", inv["id"], " ".join(bits), "Related investigations") if bits else None


def _stats_item(inv: dict) -> Item | None:
    s = inv["stats"]
    if not s:
        return None
    roles = {"ambient": "the air around the flame", "oxidizer_stream": "the gas flowing out of the burner, not the air around the flame"}
    bits = [f"{inv['name']} parsed test table: {s['tests']} tests."]
    for role, info in s["o2_by_role"].items():
        bits.append(f"Oxygen ({roles.get(role, role)}): {_range_text(info['range'], 3, 'mole fraction')}.")
    bits.append(f"Pressure: {_range_text(s['pressure_psi'], 1, 'psi')}.")
    if s["fuels"]:
        bits.append("Fuels tested: " + ", ".join(f"{k} ({n})" for k, n in s["fuels"].items()) + ".")
    if s["outcomes"]:
        bits.append("Outcomes: " + ", ".join(f"{k.replace('_', ' ')} ({n})" for k, n in s["outcomes"].items()) + ".")
    if s["varied"]:
        bits.append("Varied between tests: " + ", ".join(v["variable"].replace("_", " ") for v in s["varied"]) + ".")
    return Item(f"S:{inv['id']}", "S", inv["id"], " ".join(bits), "Test summary")


def _row_items(inv: dict, data_dir: Path, manifest_entry: dict, role_by_file: dict[str, str]) -> list[Item]:
    out = []
    for t_no, table in enumerate(manifest_entry["tables"], 1):
        if table.get("superseded_by"):                  # its rows are indexed once, from the workbook table
            continue
        name = Path(table["file"]).name
        text = (data_dir / "snapshot" / table["file"]).read_bytes().decode("utf-8-sig", errors="replace")
        reader = csv.reader(io.StringIO(text))
        header = [h.strip() for h in next(reader, [])]
        short = doc_short(name, inv["id"]).replace("Experimental table_", "").replace("Workbook table_", "")
        note = {"oxidizer_stream": " (the oxygen value is the burner stream, not the air around the flame)"}.get(role_by_file.get(name, ""), "")
        for row_no, row in enumerate(reader, start=2):
            pairs = [f"{h or f'column {i + 1}'}: {v.strip()}" for i, (h, v) in enumerate(zip(header, row)) if v.strip()]
            if not pairs:
                continue
            body = "; ".join(pairs)[:ROW_CHARS] + note
            out.append(Item(f"T:{inv['id']}:{t_no}:row{row_no}", "T", inv["id"], f"{inv['name']} test table {short}, row {row_no}: {body}",
                            f"test table {short}, row {row_no}", file=name, row=row_no))
    return out


def _doc_items(inv: dict, data_dir: Path) -> list[Item]:
    out = []
    read = [d for d in inv["documents"] if d["status"] == "read" and d.get("text_file")]
    for d_no, doc in enumerate(sorted(read, key=lambda d: d["file"]), 1):
        text = (data_dir / "snapshot" / doc["text_file"]).read_text(encoding="utf-8")
        short = doc_short(doc["file"], inv["id"])
        marks = list(SECTION.finditer(text))
        sections = [(None, text)] if not marks else [
            (m.group(1) or m.group(2), text[m.end(): marks[i + 1].start() if i + 1 < len(marks) else len(text)])
            for i, m in enumerate(marks)]
        for page, body in sections:
            is_sheet = bool(page) and not page.isdigit()
            for n, chunk in enumerate(passages(body, 800), 1):
                key = f"D:{inv['id']}:d{d_no}:{'s' if is_sheet else 'p'}{page or 0}:{n}"
                where = f"{short}" + (f", sheet {page}" if is_sheet else f", page {page}" if page else "")
                out.append(Item(key, "D", inv["id"], f"{inv['name']} document {where}: {chunk}", where, file=doc["file"], page=page))
    return out


def _publication_items(inv: dict) -> list[Item]:
    out = []
    for n, p in enumerate(inv["publications"], 1):
        text = f"{inv['name']} publication: {p.get('title') or 'Untitled'}."
        if p.get("authors"):
            text += f" Authors: {p['authors']}."
        text += f" DOI: {p['doi']}." if p.get("doi") else " No DOI listed."
        if p.get("status"):
            text += f" Status: {p['status']}."
        out.append(Item(f"P:{inv['id']}:{n}", "P", inv["id"], text, "publication list"))
    return out


def _files_item(inv: dict) -> Item | None:
    if not inv["file_inventory"]:
        return None
    size = lambda b: f"{b / 1e9:.1f} GB" if b >= 1e9 else f"{b / 1e6:.1f} MB" if b >= 1e6 else f"{b / 1e3:.0f} KB"  # noqa: E731
    parts = [f"{folder}: {f['files']} file{'s' if f['files'] != 1 else ''}, {size(f['bytes'])}"
             + (" (raw data, never downloaded)" if folder == "Raw Data" else "")
             for folder, f in sorted(inv["file_inventory"].items(), key=lambda kv: -kv[1]["bytes"])]
    text = f"{inv['name']}: PSI holds these files. " + "; ".join(parts) + "."
    read = [doc_short(d["file"], inv["id"]) for d in inv["documents"] if d["status"] == "read"]
    unread = [f"{doc_short(d['file'], inv['id'])} ({d['status'].replace('not read: ', '')})" for d in inv["documents"] if d["status"] != "read"]
    if read:
        text += " Documents read for SpaceSweepers: " + "; ".join(read) + "."
    if unread:
        text += " Documents not read: " + "; ".join(unread) + "."
    named = [n for f in inv["file_inventory"].values() for n in f["names"]]
    if named:
        text += " Other files listed: " + "; ".join(doc_short(n, inv["id"]) for n in named[:40]) + ("…" if len(named) > 40 else ".")
    return Item(f"F:{inv['id']}", "F", inv["id"], text, "file list")


def _simulation_items(inv: dict) -> list[Item]:
    sim = inv.get("simulated_data")
    out = []
    for n, row in enumerate((sim or {}).get("rows", []), 1):
        body = "; ".join(f"{k}: {v.strip()}" for k, v in row.items() if v and v.strip())
        out.append(Item(f"V:{inv['id']}:{n}", "V", inv["id"], f"{inv['name']} simulated data list, entry {n} (a simulation by the investigators, not an experiment; "
                                                           f"the data file is stored unchanged in this snapshot): {body}.", f"simulated data list, entry {n}"))
    return out


def build_items(catalog: Catalog, data_dir: Path) -> list[Item]:
    names = {i["id"]: i["name"] for i in catalog.ordered()}
    role_by_file = {t["file"]: t["o2_role"] for t in catalog.tests if t["o2_role"]}
    items: list[Item] = []
    for inv in catalog.ordered():
        items += _record_items(inv)
        items.append(_facts_item(inv))
        items.append(_method_item(inv))
        for maker in (_tags_item, _stats_item, _files_item):
            made = maker(inv)
            if made:
                items.append(made)
        lineage = _lineage_item(inv, names)
        if lineage:
            items.append(lineage)
        items += _publication_items(inv)
        items += _simulation_items(inv)
        items += _doc_items(inv, data_dir)
        items += _row_items(inv, data_dir, catalog.manifest["investigations"][inv["id"]], role_by_file)
    return items


def build_library(catalog: Catalog, data_dir: Path) -> Library:
    items = build_items(catalog, data_dir)
    by_id: dict[str, Item] = {}
    for item in items:
        if item.id in by_id:
            raise ValueError(f"duplicate evidence id {item.id}")
        by_id[item.id] = item
    db = sqlite3.connect(":memory:", check_same_thread=False)
    db.execute("CREATE VIRTUAL TABLE items USING fts5(id UNINDEXED, kind UNINDEXED, psi UNINDEXED, head, body, "
               "tokenize='porter unicode61')")
    heads = {i["id"]: f"{i['name']} {i['id']} {i['title']}" for i in catalog.ordered()}
    db.executemany("INSERT INTO items(id, kind, psi, head, body) VALUES (?,?,?,?,?)",
                   [(i.id, i.kind, i.psi, heads.get(i.psi, i.psi), i.text) for i in items])
    unread = [{"psi": inv["id"], "file": d["file"], "reason": d["status"].replace("not read: ", "")}
              for inv in catalog.ordered() for d in inv["documents"] if d["status"] != "read"]
    return Library(items=by_id, catalog=catalog, unread=unread, data_dir=data_dir, _db=db)


@lru_cache
def get_library(data_dir: Path) -> Library:
    return build_library(get_catalog(data_dir), data_dir)
