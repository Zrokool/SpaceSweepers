"""Concept questions ("What is a cool flame?"): show PSI's own words, never a paraphrase.

Code finds the sentences in PSI's reports and science documents that talk about the term in a defining way and ranks them. SI may
point at the best candidate (agent 17, Nimbus/agents/17-definition-pointer.md); code checks that the sentence really contains the
term and a defining cue, and shows it verbatim with its document and page. If PSI never defines the term, the card says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.insights.library import Item, Library
from app.nimbus.method import sentences

ASK = re.compile(r"^\s*(?:what(?:'s| is| are| does)|define|explain|describe|tell me about|what do you mean by)\s+(?:a |an |the )?(?P<term>[a-z][a-z0-9\- ]{2,40}?)(?:\s+(?:and|in|for|mean|means|matter|matters|work|works|do|used|differ|relate)\b|\s*[?.!,;:]|$)", re.I)
NOT_A_TERM = re.compile(r"\b(investigations?|dashboard|chat|psi|data|tests?|results?|findings?|publications?|documents?|files?|tables?|spacesweepers?|nasa|difference|best|most|which|how many)\b", re.I)
CUE = re.compile(r"\b(?:is|are|was|were) (?:a|an|the|defined|characterized|known|called|referred|one)\b(?! (?:function|measure|result|part|factor|key|major|primary|main)\b)|\brefers? to\b|\bdefined as\b|\bknown as\b|\bcalled\b|\bwe (?:define|call)\b|\bmeans?\b|\bcharacteri[sz]ed by\b", re.I)
MIN_SCORE = 5.0
PREFIX = re.compile(r"^.*?\b(?:page \d+|Approach|Objective|Hypothesis|Description|Impacts?|[A-Z][a-z]+ benefits?)\s*:\s*")


@dataclass
class Candidate:
    id: str
    sentence: str
    score: float
    where: str
    item: Item


def read_term(question: str, named_investigations: list[str] | None = None) -> str | None:
    """The thing being asked about, or None when the question is not a plain "what is X" question."""
    if named_investigations:
        return None
    m = ASK.match(" ".join((question or "").split()))
    term = (m.group("term").strip().lower() if m else "")
    return term if term and not NOT_A_TERM.search(term) and 1 <= len(term.split()) <= 4 else None


def _singular(term: str) -> str:
    return re.sub(r"(?<=[a-z])s$", "", term)


def candidates(library: Library, term: str, limit: int = 6) -> list[Candidate]:
    stem = re.escape(_singular(term))
    pat = re.compile(rf"(?<![a-z]){stem}s?(?![a-z])", re.I)
    out, seen = [], set()
    for it in library.search(term, kinds="DR", limit=80):
        text = PREFIX.sub("", it.text, count=1)
        for n, s in enumerate(sentences(text), 1):
            m = pat.search(s)
            key = s.strip().lower()
            whole = s.strip()[:1].isupper() or s.strip()[:1].isdigit()                      # a passage can begin or end mid-sentence: only whole sentences
            if not m or key in seen or not whole or not s.rstrip().endswith((".", "!", ";")) or not 40 <= len(s) <= 420 or s.rstrip().endswith(("Fig.", "Figs.", "Eq.", "et al.")):
                continue
            seen.add(key)
            after = s[m.end():m.end() + 70]
            score = 0.0
            if re.match(r"\s*(,|\(|—|-)?\s*(is|are|refers?|means?)\b", after, re.I):
                score += 6
            if CUE.search(after):
                score += 3
            if re.search(r"\b(known as|called|defined as)\b[^.]{0,30}" + stem, s, re.I):
                score += 3
            score -= abs(len(s) - 160) / 200
            score -= 2 * len(re.findall(r"(?<![\w'])[b-hj-zB-HJ-Z](?![\w'])", s))        # text extracted from a PDF can split a word ("b urns"): prefer clean sentences
            out.append(Candidate(f"{it.id}#{n}", s.strip(), score, it.where, it))
    out.sort(key=lambda c: -c.score)
    return out[:limit]


WHY = re.compile(r"\b(improv\w+|important|significan\w+|safety|understanding|benefit\w*|enable\w*|critical|relevan\w+|applicab\w+|help\w*)\b", re.I)
WHY_ASKED = re.compile(r"\b(why|matter|important|relevan\w+|care|significan\w+)\b", re.I)


def why_it_matters(cands: list[Candidate], chosen: Candidate | None, term: str) -> Candidate | None:
    """When the user also asked why it matters: the cleanest sentence about the term that says what it helps with. Same rules D-1."""
    pool = [c for c in cands if c is not chosen and WHY.search(c.sentence) and re.search(re.escape(_singular(term)), c.sentence, re.I)]
    return max(pool, key=lambda c: c.score, default=None)


def verify(sentence: str, term: str) -> bool:
    """Rule D-1: the sentence contains the term; rule D-2: it contains a defining cue after it."""
    m = re.search(rf"(?<![a-z]){re.escape(_singular(term))}s?(?![a-z])", sentence, re.I)
    return bool(m and CUE.search(sentence[m.end():m.end() + 90]))


def card(term: str, chosen: Candidate | None, others: list[Candidate], why: Candidate | None = None) -> dict:
    if not chosen:
        return {"goal": "definition", "title": f"PSI's documents and what they say about \"{term}\"", "scope": term, "metrics": [], "table": None, "links": [],
                "headline": [f"PSI's reports and science documents that this chat holds do not define \"{term}\" in a sentence of their own."],
                "caveats": ["The documents were searched for a sentence that names the term and defines it. Related passages are in the sources panel when the chat found any."]}
    it = chosen.item
    return {"goal": "definition", "title": f"What PSI's documents say: {term}", "scope": term, "metrics": [], "table": None, "links": [],
            "headline": [chosen.sentence, *([why.sentence] if why else [])],
            "quote": {"text": chosen.sentence, "where": it.where, "psi": it.psi, "file": it.file, "page": it.page},
            "quote2": ({"label": "Why PSI says it matters", "text": why.sentence, "where": why.item.where} if why else None),
            "caveats": ["This is PSI's own sentence, word for word. It is one investigation's wording, not a textbook definition.",
                        *([f"{len(others)} other passage{'s' if len(others) != 1 else ''} also mention the term; open the sources panel to read them."] if others else [])]}
