"""Tag an investigation's fuels, hardware, sensors and fire-safety pillars from its record text.

Plain word matching against data/vocabulary.yaml: deterministic, no SI. Each tag
keeps the field and sentence it was found in, so it can be checked by a reader.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import yaml

TEXT_FIELDS = ["title", "acronym", "objective", "approach", "hypothesis", "keywords_text", "hardware_text"]
# Hardware and sensors are read only from where a record describes its own setup. Objectives and
# hypotheses often mention other work ("based on drop-tower results"), which gave wrong tags.
SETUP_FIELDS = ["hardware_text", "approach", "keywords_text", "title"]
# What a record says its research informs is in its purpose and impact statements, not in its title or setup.
EQUIPMENT_FIELDS = ["objective", "hypothesis", "impacts", "approach"]


@lru_cache
def load_vocabulary(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def term_pattern(term: str) -> re.Pattern:
    # Whole words only, so "CIR" doesn't match "circular"; short all-caps terms are case-sensitive.
    flags = 0 if term.isupper() and len(term) <= 5 else re.I
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", flags)


def sentence_at(text: str, start: int, end: int, limit: int = 260) -> str:
    """The sentence around text[start:end], trimmed."""
    left = max(text.rfind(". ", 0, start), text.rfind("\n", 0, start))
    right_candidates = [i for i in (text.find(". ", end), text.find("\n", end)) if i != -1]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    quote = " ".join(text[left + 1:right].split())
    return quote if len(quote) <= limit else quote[:limit].rsplit(" ", 1)[0] + "…"


def find_terms(record: dict, terms: list[str], fields: list[str] = TEXT_FIELDS) -> list[dict]:
    """First match of each term across the record's text fields."""
    found = []
    for term in terms:
        pattern = term_pattern(term)
        for field in fields:
            text = record.get(field) or ""
            m = pattern.search(text)
            if m:
                found.append({"term": term, "field": field, "quote": sentence_at(text, m.start(), m.end())})
                break
    return found


def tag(record: dict, vocabulary: dict) -> dict:
    fuels = []
    for fuel_class, terms in vocabulary["fuels"].items():
        fuels += [{**hit, "fuel_class": fuel_class} for hit in find_terms(record, terms)]
    labelled = lambda group: [{"label": label, **hits[0]} for label, terms in vocabulary[group].items()  # noqa: E731
                              if (hits := find_terms(record, terms, SETUP_FIELDS))]
    # A Ground investigation analyses or models flight data: it ran no hardware and used no sensors of its own.
    ground = record.get("project_type") == "Ground"
    solid_emulation = find_terms(record, vocabulary["solid_emulation"])
    if solid_emulation:
        # An emulator burns a gas to imitate solids and liquids: the "solid fuel" in its text is what it imitates.
        fuels = [f for f in fuels if f["fuel_class"] == "gas"]
    return {
        "fuels": fuels,
        "fuel_classes": sorted({f["fuel_class"] for f in fuels}),
        "solid_emulation": solid_emulation,
        "hardware": [] if ground else labelled("hardware"),
        "sensors": [] if ground else labelled("sensors"),
        "equipment": [{"label": label, **hits[0]} for label, terms in vocabulary["equipment"].items()
                      if (hits := find_terms(record, terms, EQUIPMENT_FIELDS))],
        "out_of_scope": find_terms(record, vocabulary["out_of_scope"]),
    }
