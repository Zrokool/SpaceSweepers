"""The catalog: everything the dashboard knows, loaded from the committed PSI snapshot.

Built once at startup from data/snapshot (records, tables, manifest), the reviewed
files in data/ (vocabulary, mappings, method flags, sources) and nothing else.
The dataset is small (26 investigations, a few thousand test values), so it is
held in memory; there is no database to keep in step with the snapshot.
"""

from __future__ import annotations

import csv
import io
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from app.analysis.attributes import load_vocabulary, tag, term_pattern
from app.analysis import outcome_layer
from app.analysis import pillars as pillar_mod
from app.analysis.taxonomy import classify, load_taxonomy
from app.psi.harmonise import harmonise_table, load_mappings
from app.psi.ledger import REASONS, load_ledger, resolve, verify_evidence

PSI_REF = re.compile(r"PSI-\d+")
NUMERIC = ("o2_fraction", "pressure_psi", "burn_time_s", "flame_temp_k", "fuel_flow_mg_s", "flow_cm_s")


def _psi_number(psi_id: str) -> int:
    return int(psi_id.split("-")[1])


def _hardware(raw) -> tuple[str, str | None]:
    """PSI gives hardware as text in full records and as {Name, Link} in search hits."""
    if isinstance(raw, dict):
        return " ".join((raw.get("Name") or "").split()), raw.get("Link") or None
    return " ".join((raw or "").split()), None


def normalise(snap: dict) -> dict:
    """One investigation in the shape the rest of the app uses. Text is kept as PSI wrote it."""
    hardware_text, hardware_link = _hardware(snap.get("experiment_hardware"))
    keywords = [k.strip() for k in re.split(r"\s{2,}", snap.get("keywords") or "") if k.strip()]
    related = sorted(set(PSI_REF.findall(f"{snap.get('related_search') or ''} {snap.get('related_record') or ''}"))
                     - {snap["id"]}, key=_psi_number)
    acronym = (snap.get("acronym") or snap.get("acronym_record") or "").strip()
    project_type = (snap.get("project_type") or "").replace(" Investigation", "") or "Unknown"
    full = snap.get("record_source") != "search listing"
    return {
        "id": snap["id"], "title": snap.get("title") or "", "acronym": acronym,
        "name": acronym or snap["id"],
        "project_type": project_type,  # Microgravity | Ground
        "research_area": snap.get("research_area") or "",
        "is_combustion": snap.get("research_area") == "Combustion Science",
        "match_reason": snap.get("match_reason"),
        "platform": (snap.get("flight_platform") or "").strip() or None,
        "sub_area": (snap.get("sub_research_area") or "").strip() or None,
        "objective": snap.get("objective") or "", "approach": snap.get("approach") or "",
        "hypothesis": snap.get("hypothesis") or "", "impacts": snap.get("research_impacts") or "",
        "hardware_text": hardware_text, "hardware_link": hardware_link,
        "keywords": keywords, "keywords_text": "; ".join(keywords),
        "related": related,
        "start_date": snap.get("start_date"), "end_date": snap.get("end_date"),
        "doi": snap.get("doi") or None, "license": snap.get("license_id") or None,
        "license_link": snap.get("license_link") or None,
        "landing_url": snap["landing_url"],
        "record_source": snap.get("record_source"), "record_complete": full,
        "record_fetched_at": snap.get("record_fetched_at"),
        "publications": snap.get("publications") or [],
        "tables_listed": [t["file"] for t in snap.get("experimental_tables") or []],
        "modeling_tables": snap.get("modeling_tables") or [],
        "file_folders": snap.get("file_folders") or {},
        "file_inventory": snap.get("file_inventory") or {},
        "images": snap.get("images") or [],
        "proposal_title": (snap.get("proposal_title") or "").strip() or None,
        "flight_program": (snap.get("flight_program") or "").strip() or None,
        "sponsor": (snap.get("sponsor") or "").strip() or None,
        "nasa_center": (snap.get("nasa_center") or "").strip() or None,
        "hardware_links": [u.strip() for u in (snap.get("hardware_links") or "").split(",") if u.strip().startswith("http")],
        "description": (snap.get("description") or "").strip(),
        "acknowledgments": (snap.get("acknowledgments") or "").strip(),
        "version": snap.get("version"), "version_reason": snap.get("version_reason"),
        "submission_date": snap.get("submission_date"), "release_date": snap.get("release_date"),
        "modified_date": snap.get("modified_date"),
    }


def _range(values: list[float]) -> list[float] | None:
    return [min(values), max(values)] if values else None


def test_stats(tests: list[dict]) -> dict:
    """Ranges, outcomes and what varied, for one investigation's harmonised tests.

    Oxygen is reported per role: a burner-stream fraction is never mixed with the
    oxygen of the surrounding atmosphere.
    """
    usable = lambda t, var: (v := t["values"].get(var)) and v["flag"] in ("ok", "approx", "range") \
        and v["value"] is not None  # noqa: E731
    numbers = lambda var, subset=tests: [t["values"][var]["value"] for t in subset if usable(t, var)]  # noqa: E731
    o2_by_role = {}
    for role in sorted({t["o2_role"] for t in tests if t["o2_role"]}):
        vals = numbers("o2_fraction", [t for t in tests if t["o2_role"] == role])
        o2_by_role[role] = {"range": _range(vals), "tests": len(vals)}
    varied, fixed = [], []
    for var in sorted({v for t in tests for v in t["values"]} - {"comment"}):
        distinct = {str(t["values"][var]["value"]).lower() for t in tests if usable(t, var)}
        if len(distinct) > 1:
            varied.append({"variable": var, "distinct": len(distinct)})
        elif len(distinct) == 1:
            fixed.append({"variable": var, "value": next(iter(distinct))})
    text = lambda var: Counter(str(t["values"][var]["value"]).lower() for t in tests if usable(t, var))  # noqa: E731
    return {
        "tests": len(tests),
        "o2_by_role": o2_by_role,
        "pressure_psi": _range(numbers("pressure_psi")),
        "fuels": dict(text("fuel").most_common()),
        "outcomes": dict(text("outcome").most_common()),
        "varied": varied, "fixed": fixed,
    }


@dataclass
class Catalog:
    manifest: dict
    investigations: dict[str, dict]
    tests: list[dict] = field(default_factory=list)
    coverage: dict[str, list[dict]] = field(default_factory=dict)
    lineage: list[dict] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)
    vocabulary: dict = field(default_factory=dict)
    taxonomy: dict = field(default_factory=dict)

    def get(self, psi_id: str) -> dict | None:
        return self.investigations.get(psi_id)

    def ordered(self) -> list[dict]:
        return sorted(self.investigations.values(), key=lambda i: _psi_number(i["id"]))

    def tests_for(self, psi_id: str) -> list[dict]:
        return [t for t in self.tests if t["investigation"] == psi_id]


FUEL_COLUMN = re.compile(r"^(fuel|material|sample material|fuel sample material|fuel type|sample type|sample \(fuel type\)|fuel bottle)$", re.I)


def read_table(snapshot: Path, table: dict) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """(header, [(row number, cells)]) of a downloaded test table. Blank rows are skipped; row 1 is the header."""
    text = (snapshot / table["file"]).read_bytes().decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    header = [h.strip() for h in next(reader, [])]
    return header, [(n, row) for n, row in enumerate(reader, start=2) if any(c.strip() for c in row)]


def table_facts(snapshot: Path, entry: dict, vocabulary: dict) -> tuple[int, list[dict]]:
    """Rows in the investigation's downloaded tables, and the fuels or materials named in their Fuel/Material column.

    Each fuel keeps the table cell it came from, so it can be checked. A value no vocabulary term matches is left out.
    """
    classes = {term: cls for cls, terms in vocabulary["fuels"].items() for term in terms}
    rows, fuels, seen = 0, [], set()
    for table in entry["tables"]:
        if table.get("superseded_by"):                  # its tests are counted in the workbook table
            continue
        header, body = read_table(snapshot, table)
        rows += len(body)
        col = next((n for n, h in enumerate(header) if FUEL_COLUMN.match(h)), None)
        if col is None:
            continue
        for row_no, cells in body:
            value = cells[col].strip() if col < len(cells) else ""
            for term in sorted(classes, key=len, reverse=True):
                if value and term not in seen and term_pattern(term).search(value):
                    seen.add(term)
                    fuels.append({"term": term, "fuel_class": classes[term], "field": "test table",
                                  "quote": f"{header[col]}: {value} ({Path(table['file']).name}, row {row_no})"})
                    break
    return rows, fuels


def build_lineage(investigations: dict[str, dict]) -> list[dict]:
    """Directed edges from each investigation's Related Investigations field.

    PSI's links are one-way (FLEX lists nothing, yet three investigations point to
    it), so each edge records who listed it. A Ground investigation that points to
    a Microgravity one is using that flight investigation's data.
    """
    edges = []
    for inv in investigations.values():
        for target in inv["related"]:
            other = investigations.get(target)
            uses_flight_data = bool(other) and inv["project_type"] == "Ground" and other["project_type"] == "Microgravity"
            edges.append({"from": inv["id"], "to": target, "listed_by": inv["id"],
                          "relation": "uses flight data from" if uses_flight_data else "related",
                          "in_scope": other is not None})
    return edges


def load_method_flags(data_dir: Path) -> dict[str, dict]:
    """SI-proposed, code-checked method flags, overridden by the team's confirmations."""
    flags: dict[str, dict] = {}
    generated = data_dir / "method_flags.json"
    if generated.exists():
        flags.update(json.loads(generated.read_text(encoding="utf-8")).get("flags", {}))
    confirmed = data_dir / "method_flags.yaml"
    if confirmed.exists():
        for psi_id, entry in (yaml.safe_load(confirmed.read_text(encoding="utf-8")) or {}).items():
            flags[psi_id] = {**flags.get(psi_id, {}), **entry, "status": "team-confirmed"}
    return flags


def _simulated_data(snapshot: Path, entry: dict, inv: dict) -> dict | None:
    """The list of data files behind a modelling study, exactly as its lab wrote it. Never part of the tests."""
    sims = entry.get("simulations")
    if not sims:
        return None
    rows = list(csv.DictReader(io.StringIO((snapshot / sims[0]["file"]).read_text(encoding="utf-8"))))
    return {"file": sims[0]["file"], "workbook": sims[0]["workbook"], "rows": rows,
            "note": (f"Simulations by the {inv['name']} investigators (a NASA-sponsored PSI study), not experiments. PSI's README lists the data files and the paper "
                     "figure each came from. The data files are stored unchanged in this snapshot; two of them are drawn below as experiment against simulation, and the conditions here are shown exactly as written.")}


def pillar_reason(code: str, other: str) -> str:
    """The reason text for a superseded table, naming the table that replaces it."""
    return f"Every test in it is in {other}, which is built from the lab's own workbook, so it is not counted again."


def load_catalog(data_dir: Path) -> Catalog:
    snapshot = data_dir / "snapshot"
    manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
    vocabulary = load_vocabulary(data_dir / "vocabulary.yaml")
    mappings = load_mappings(data_dir / "mappings")          # hand-reviewed; they win over the generated ledger
    ledger = load_ledger(data_dir / "table_mappings.json")
    taxonomy = load_taxonomy(data_dir / "taxonomy.yaml")
    pillar_evidence, pillar_team = pillar_mod.load_evidence(data_dir)
    doc_outcomes = outcome_layer.load(data_dir)
    method_flags = load_method_flags(data_dir)

    investigations: dict[str, dict] = {}
    for path in (snapshot / "records").glob("PSI-*.json"):
        inv = normalise(json.loads(path.read_text(encoding="utf-8")))
        inv["attributes"] = tag(inv, vocabulary)
        investigations[inv["id"]] = inv
    for psi_id, inv in investigations.items():
        # The fuels and materials PSI's own test tables name, added to what the record text names.
        rows, table_fuels = table_facts(snapshot, manifest["investigations"][psi_id], vocabulary)
        inv["table_rows"] = rows
        a = inv["attributes"]
        known = {f["term"] for f in a["fuels"]}
        a["fuels"] += [f for f in table_fuels if f["term"] not in known]
        if a["solid_emulation"]:
            a["fuels"] = [f for f in a["fuels"] if f["fuel_class"] == "gas"]
        a["fuel_classes"] = sorted({f["fuel_class"] for f in a["fuels"]})

    tests, coverage = [], {}
    for psi_id, entry in manifest["investigations"].items():
        coverage[psi_id] = []
        for table in entry["tables"]:
            name = Path(table["file"]).name
            if table.get("superseded_by"):
                row = {"file": name, "status": "superseded", "reason_code": "superseded", "reason": pillar_reason("superseded", Path(table["superseded_by"]).name), "tests": 0}
                row.update(classify(taxonomy, read_table(snapshot, table)[0], investigations[psi_id], row))
                coverage[psi_id].append(row)
                continue
            decision = resolve(name, table["sha256"], mappings, ledger)        # a mapping only applies to the exact table it was made for
            if decision["source"] == "hand-reviewed" and decision["mapping"] and decision["mapping"].get("evidence"):
                if verify_evidence(snapshot, decision["mapping"]["evidence"]):   # its quotes must still be in the PSI documents
                    decision = {"mapping": None, "status": "stale", "reason_code": "evidence_missing", "reason": REASONS["evidence_missing"], "source": "hand-reviewed"}
            if decision["mapping"] is None:
                row = {"file": name, "status": decision["status"], "reason_code": decision["reason_code"],
                         "reason": decision["reason"], "tests": 0}
            else:
                result = harmonise_table((snapshot / table["file"]).read_bytes(), decision["mapping"], name)
                layer = outcome_layer.apply(result["tests"], psi_id, name, table["sha256"], doc_outcomes)
                result["coverage"]["document_outcomes"] = layer
                tests += result["tests"]
                row = {**result["coverage"], "status": "parsed", "mapping_source": decision["source"],
                         "has_outcome": "outcome" in decision["mapping"]["columns"]}
            if psi_id in investigations:                                       # family and readiness tier, with what they matched
                row.update(classify(taxonomy, read_table(snapshot, table)[0], investigations[psi_id], row))
            coverage[psi_id].append(row)
        for missing in entry["not_downloaded"]:
            coverage[psi_id].append({"file": missing["file"], "status": f"not downloaded: {missing['reason']}",
                                     "tests": 0})
        if psi_id in investigations:
            # Reports, Science Documents and ReadMe files: which were read, and why the others weren't.
            investigations[psi_id]["documents"] = entry.get("documents", [])

    for psi_id, inv in investigations.items():
        inv["simulated_data"] = _simulated_data(snapshot, manifest["investigations"][psi_id], inv)
        inv["analyzed"] = [{"file": f["file"].rsplit("/", 1)[-1], "figure": f.get("figure")} for f in manifest["investigations"][psi_id].get("analyzed", [])]

    lineage = build_lineage(investigations)
    for inv in investigations.values():
        own = [t for t in tests if t["investigation"] == inv["id"]]
        inv["stats"] = test_stats(own) if own else None
        inv["tables"] = coverage.get(inv["id"], [])
        # Whether condition data is known, unknown or not expected, said plainly.
        inv.setdefault("documents", [])
        if own:
            inv["tables_status"] = "parsed"
        elif not inv["record_complete"]:
            inv["tables_status"] = "unknown: PSI's full record wasn't available when the snapshot was taken"
        elif any(t["status"] == "stale" for t in inv["tables"]):
            inv["tables_status"] = "stale: a table changed after it was mapped; data refresh needed"
        elif any(t["status"] == "not mappable" for t in inv["tables"]):
            inv["tables_status"] = "downloaded; not mappable: " + "; ".join(sorted({t["reason"] for t in inv["tables"] if t["status"] == "not mappable"}))
        elif any(t["status"] == "no mapping yet" for t in inv["tables"]):
            inv["tables_status"] = "downloaded; its columns haven't been mapped yet"
        elif inv["tables"]:
            inv["tables_status"] = "listed by PSI but not downloaded"
        else:
            inv["tables_status"] = "PSI lists no test table"
        inv["pillars"] = pillar_mod.assemble(inv, pillar_evidence.get(inv["id"]), pillar_team.get(inv["id"]),
                                             pillar_mod.data_links(inv, own, vocabulary["pillar_data_links"]))
        inv["uses_data_from"] = [e["to"] for e in lineage if e["from"] == inv["id"]
                                 and e["relation"] == "uses flight data from"]
        inv["data_used_by"] = [e["from"] for e in lineage if e["to"] == inv["id"]
                               and e["relation"] == "uses flight data from"]
        inv["related_in"] = sorted({e["from"] for e in lineage if e["to"] == inv["id"]}, key=_psi_number)
        # Acronyms of the flight investigations this one builds on (FLEX, SAME…), for the method checks.
        inv["source_names"] = [investigations[i]["acronym"] for i in inv["uses_data_from"] if investigations[i]["acronym"]]
        inv["method"] = method_flags.get(inv["id"]) or {
            "flag": "unverified", "status": "not assessed",
            "reason": "The Investigator hasn't read this investigation's Approach text yet."}

    sources_path = data_dir / "sources.yaml"
    sources = yaml.safe_load(sources_path.read_text(encoding="utf-8"))["sources"] if sources_path.exists() else []
    return Catalog(manifest=manifest, investigations=investigations, tests=tests, coverage=coverage,
                   lineage=lineage, sources=sources, vocabulary=vocabulary, taxonomy=taxonomy)


@lru_cache
def get_catalog(data_dir: Path) -> Catalog:
    return load_catalog(data_dir)
