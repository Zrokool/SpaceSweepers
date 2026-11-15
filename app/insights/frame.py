"""Read a question (code, no SI): which investigations it names, what topics, numbers and kind of question.

The result is shown to the user as chips ("About: FLEX · Topic: extinction") and steers the tools,
so the retrieval never depends on the model understanding the question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.catalog import Catalog
from app.psi.units import convert

# Measurement and safety topics, written as words a question might use. CO, CO2, HF, HCN are case-sensitive.
TOPICS: dict[str, list[str]] = {
    "oxygen": ["oxygen", "O2", "XO2", "oxidizer"],
    "pressure": ["pressure", "psi", "atm", "bar"],
    "temperature": ["temperature", "heating", "overheat", "cool flame", "hot"],
    "airflow": ["airflow", "air flow", "ventilation", "flow velocity", "flow speed", "fan", "forced flow", "coflow", "co-flow"],
    "smoke": ["smoke", "aerosol", "particulate", "particle", "particles", "soot"],
    "combustion gases": ["carbon monoxide", "CO", "CO2", "carbon dioxide", "HCN", "HF", "toxic gas"],
    "humidity": ["humidity", "moisture", "water vapor"],
    "extinction": ["extinction", "extinguish", "extinguishment", "suppress", "suppression", "suppressant"],
    "flammability": ["flammability", "flammable", "ignition", "ignite", "flame spread", "burning rate", "burn rate"],
    "detection": ["detect", "detector", "detection"],
}
CASE_SENSITIVE = {"CO", "CO2", "HF", "HCN", "O2", "XO2", "psi", "atm"}
# Acronyms that are also ordinary English words: only an upper-case match counts as naming the investigation.
PLAIN_WORDS = {"same", "slice", "spice", "bass", "flex"}
GROUPS = {"SAFFIRE": "SAFFIRE", "ACME": "ACME"}           # a bare family name means every member
INTENTS = {
    "count": r"\bhow many\b|\bnumber of\b|\bcount\b",
    "compare": r"\bcompar\w*|\bdifferen\w*|\bversus\b|\bvs\.?\b|\bsimilar\w*|\balike\b",
    "list": r"\bwhich\b|\blist\b|\bwhat investigations\b|\bwho\b|\bwhere\b",
    "tests": r"\btests?\b|\brows?\b|\bruns?\b|\bconditions?\b|\bmeasured?\b|\brecorded?\b",
    "publications": r"\bpublications?\b|\bpapers?\b|\bpublished\b|\bcite\b|\bcitation\b|\bdoi\b",
    "files": r"\bfiles?\b|\bdocuments?\b|\breports?\b|\breadme\b|\bdata available\b",
    "safety": r"\bis there (?:a )?(?:fire|smoke)\b|\b(?:on|in) fire\b|\bfire (?:in|on|aboard) the\b|\bwhat (?:should|do) (?:i|we) do\b|\bemergency\b|\bevacuat\w*",
    "lineage": r"\bflight data\b|\bground (?:stud|investigation)\w*|\bbased on\b|\bbuilds? on\b|\buses? (?:the )?data\b",
}
METHOD_WORDS = {"experimental": r"\bexperimental(?:ly)?\b|\bphysical tests?\b|\bflown\b|\bactual experiments?\b|\bwere experiments?\b",
                "simulation": r"\bsimulat\w*|\bmodell?ing\b|\bCFD\b|\bnumerical\b|\bcomputational\b"}
FOLLOW_UP = re.compile(r"\b(it|its|they|their|them|that|this|those|these|the same|also|and what about|what about)\b", re.I)


@dataclass
class Frame:
    question: str
    psi_ids: list[str] = field(default_factory=list)       # investigations named (or carried over)
    carried: bool = False
    topics: list[str] = field(default_factory=list)
    fuels: list[str] = field(default_factory=list)
    fuel_class: str | None = None
    methods: list[str] = field(default_factory=list)
    intents: list[str] = field(default_factory=list)
    project_type: str | None = None                       # "Microgravity" | "Ground"
    o2: dict | None = None                                # {"min": 0.3, "max": None, "text": "oxygen ≥ 30%"}
    pressure: dict | None = None                          # in psi
    search_text: str = ""                                 # the question without the investigation names

    def chips(self, names: dict[str, str]) -> list[dict]:
        out = [{"kind": "about", "label": names.get(i, i), "psi": i} for i in self.psi_ids]
        if self.carried:
            out.append({"kind": "carried", "label": "from the last answer"})
        out += [{"kind": "topic", "label": t} for t in self.topics]
        out += [{"kind": "fuel", "label": f} for f in self.fuels]
        out += [{"kind": "method", "label": m} for m in self.methods]
        if self.project_type:
            out.append({"kind": "type", "label": self.project_type})
        for key, label in (("o2", self.o2), ("pressure", self.pressure)):
            if label:
                out.append({"kind": "number", "label": label["text"]})
        return out


class QuestionReader:
    def __init__(self, catalog: Catalog) -> None:
        self.catalog = catalog
        self.names = {i["id"]: i["name"] for i in catalog.ordered()}
        aliases: dict[str, list[str]] = {}
        for inv in catalog.ordered():
            candidates = {inv["id"], inv["id"].replace("-", " ")}
            for part in re.split(r"\s*/\s*", inv["acronym"] or ""):
                part = part.strip()
                if part:
                    candidates.add(part)
                    if part.startswith("ACME ") and len(part) > 8:
                        candidates.add(part[5:])             # "CFI-G", "s-Flame", "E-FIELD Flames"
            for c in candidates:
                aliases.setdefault(c, []).append(inv["id"])
        for group, prefix in GROUPS.items():
            aliases[group] = [i["id"] for i in catalog.ordered() if (i["acronym"] or "").upper().startswith(prefix)]
        self.aliases = dict(sorted(aliases.items(), key=lambda kv: -len(kv[0])))      # longest first
        self.fuel_terms = {term: cls for cls, terms in catalog.vocabulary["fuels"].items() for term in terms}

    # ------------------------------------------------------------ pieces
    def _investigations(self, text: str, groups: bool = True) -> tuple[list[str], str]:
        """Investigations named in `text`, in the order they appear. With groups=False a bare family name ("Saffire") names none."""
        position: dict[str, int] = {}
        work = text
        for m in re.finditer(r"\bPSI[- ]?(\d{1,3})\b", work, re.I):
            psi_id = f"PSI-{int(m.group(1))}"
            if psi_id in self.names:
                position.setdefault(psi_id, m.start())
        work = re.sub(r"\bPSI[- ]?\d{1,3}\b", lambda m: " " * len(m.group()), work, flags=re.I)
        for alias, ids in self.aliases.items():
            if alias.upper().startswith("PSI") or (not groups and alias in GROUPS):
                continue
            plain = alias.lower() in PLAIN_WORDS
            flags = 0 if plain or len(alias) <= 3 else re.I
            pattern = re.compile(rf"(?<![A-Za-z0-9-]){re.escape(alias)}(?![A-Za-z0-9]|-[A-Za-z0-9])", flags)
            first = pattern.search(work)
            if first:
                for i in ids:
                    position.setdefault(i, first.start())
                work = pattern.sub(lambda m: " " * len(m.group()), work)
        return sorted(position, key=lambda i: (position[i], int(i.split("-")[1]))), re.sub(r"\s+", " ", work).strip()

    def _topics(self, text: str) -> list[str]:
        out = []
        for topic, words in TOPICS.items():
            for w in words:
                flags = 0 if w in CASE_SENSITIVE else re.I
                if re.search(rf"(?<![A-Za-z0-9]){re.escape(w)}(?![A-Za-z0-9])", text, flags):
                    out.append(topic)
                    break
        return out

    def _fuels(self, text: str) -> tuple[list[str], str | None]:
        found = []
        for term in sorted(self.fuel_terms, key=len, reverse=True):
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", text, re.I) and not any(term.lower() in f.lower() for f in found):
                found.append(term)
        classes = {self.fuel_terms[t] for t in found}
        return found[:4], (next(iter(classes)) if len(classes) == 1 else None)

    @staticmethod
    def _bound(text: str, value: float, scale: float = 1.0) -> tuple[float | None, float | None]:
        """A one-sided bound from words near the number, else a narrow window around it."""
        low = re.search(r"(above|over|at least|more than|greater than|higher than|≥|>=|>)\s*$", text, re.I)
        high = re.search(r"(below|under|at most|less than|lower than|≤|<=|<)\s*$", text, re.I)
        if low:
            return value, None
        if high:
            return None, value
        return value - 0.02 * scale, value + 0.02 * scale

    def _numbers(self, text: str) -> tuple[dict | None, dict | None]:
        o2 = pressure = None
        m = (re.search(r"(?P<pre>[^.?!]{0,24}?)(\d+(?:\.\d+)?)\s*(?:%|percent)\s*(?:oxygen|O2|O₂)", text, re.I)
             or re.search(r"(?:oxygen|O2|O₂|XO2)(?P<pre>[^0-9]{0,24}?)(\d+(?:\.\d+)?)\s*(%|percent)?", text, re.I))
        if m:
            raw = float(m.group(2))
            value = raw / 100 if raw > 1 or "%" in m.group(0) or "percent" in m.group(0).lower() else raw
            if 0 < value <= 1:
                lo, hi = self._bound(m.group("pre") or "", value, 1.0)
                o2 = {"min": lo, "max": hi, "text": f"oxygen {'≥ ' if lo is not None and hi is None else '≤ ' if hi is not None and lo is None else '≈ '}{value:.0%}"}
        m = re.search(r"(?P<pre>[^.?!]{0,24}?)(\d+(?:\.\d+)?)\s*(psi|atm|bar|mmhg|kpa)\b", text, re.I)
        if m:
            psi = convert(float(m.group(2)), m.group(3), "pressure_psi")
            lo, hi = self._bound(m.group("pre") or "", psi, psi * 2.5)          # no comparator: about ±5%
            pressure = {"min": lo, "max": hi, "text": f"pressure {'≥ ' if lo is not None and hi is None else '≤ ' if hi is not None and lo is None else '≈ '}{psi:.1f} psi"}
        return o2, pressure

    # ------------------------------------------------------------ the whole question
    def read(self, question: str, previous: list[str] | None = None) -> Frame:
        text = re.sub(r"\s+", " ", question).strip()[:500]
        ids, rest = self._investigations(text)
        frame = Frame(question=text)
        frame.psi_ids = ids
        if not ids and previous and (FOLLOW_UP.search(text) or len(text.split()) <= 6):
            frame.psi_ids, frame.carried = [i for i in previous if i in self.names][:4], True
        frame.topics = self._topics(rest)
        frame.fuels, frame.fuel_class = self._fuels(rest)
        frame.methods = [m for m, pat in METHOD_WORDS.items() if re.search(pat, rest, re.I)]
        frame.intents = [k for k, pat in INTENTS.items() if re.search(pat, rest, re.I)]
        if re.search(r"\bground\b", rest, re.I) and not re.search(r"\bground[- ]based\b", rest, re.I):
            frame.project_type = "Ground"
        elif re.search(r"\bmicrogravity\b|\bflight\b|\bflown\b|\bISS\b", rest, re.I) and "microgravity" in rest.lower():
            frame.project_type = "Microgravity"
        frame.o2, frame.pressure = self._numbers(rest)
        frame.search_text = rest
        return frame


def reader_for(catalog: Catalog) -> QuestionReader:
    cached = getattr(catalog, "_reader", None)
    if cached is None:
        cached = QuestionReader(catalog)
        catalog._reader = cached                     # built once per loaded catalog
    return cached
