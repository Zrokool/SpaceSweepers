"""Evidence hygiene: PSI text is data. A passage that reads like an instruction to the assistant is held back from the prompt.

Fixed rules in code, no SI (OWASP LLM01 indirect prompt injection, LLM04 poisoned data). A passage that imitates a numbered evidence entry or a chat role is held back
too, so what remains cannot forge one. Control and invisible characters are removed; the layout of a passage (its line breaks) is kept,
because the model reads test rows better that way.
"""

from __future__ import annotations

import dataclasses
import re

from app.insights.library import Item

INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff]")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# (rule, what it means, pattern). Written to match instructions aimed at an assistant, not the ordinary words of a lab report.
RULES = [
    ("H-OVERRIDE", "tells the reader to ignore or override its instructions",
     re.compile(r"\b(ignore|disregard|forget|override|bypass)\b[^.?!]{0,50}\b(previous|prior|above|earlier|preceding|your|all|any)\b[^.?!]{0,40}\b(instruction|prompt|rule|guideline|direction|constraint|restriction|guardrail)s?\b", re.I)),
    ("H-ROLE", "tries to give the reader a new role",
     re.compile(r"\b(you are now|from now on,? you|developer mode|jailbreak|do anything now|pretend (that )?you (are|have|can)|you have no (rules|restrictions|limits))\b", re.I)),
    ("H-FORGED", "contains a forged chat or system marker",
     re.compile(r"(<\|(im_start|im_end|system|assistant|user|endoftext)\|>|\[/?(INST|SYS)\]|<<\s*SYS\s*>>|(?m:^\s*(system|assistant|developer)\s*:\s))", re.I)),
    ("H-FAKE-ENTRY", "imitates a numbered evidence entry", re.compile(r"(?m:^\s*E\d{1,2}\.\s*\[)")),
    ("H-LEAK", "asks the reader to reveal its instructions",
     re.compile(r"\b(reveal|print|repeat|output|disclose)\b[^.?!]{0,40}\b(system prompt|your (instruction|prompt|rule)s?|hidden (prompt|instruction)s?)\b", re.I)),
]


def scrub_evidence(items: list[Item]) -> tuple[list[Item], list[dict]]:
    """(the items to use, a record of each passage held back). Surviving items keep their layout."""
    kept, held = [], []
    for it in items:
        raw = INVISIBLE.sub("", CONTROL.sub(" ", it.text))
        hit = next(((rule, why) for rule, why, rx in RULES if rx.search(raw)), None)
        if hit:
            held.append({"id": it.id, "rule": hit[0], "why": hit[1]})
            continue
        kept.append(dataclasses.replace(it, text=raw) if raw != it.text else it)
    return kept, held
