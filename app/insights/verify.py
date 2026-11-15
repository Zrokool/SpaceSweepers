"""Nimbus checks for SI Insights: every sentence the model writes is checked here, by fixed rules (no SI).

A sentence is kept only if it passes all of them. A removed sentence is shown to the user with the
rule that removed it. The rules are written in Nimbus/README.md and Nimbus/agents/12-analyst.md.

    C-CITE     it must cite evidence, and only evidence that exists
    C-SCOPE    it must not say a fire is occurring, predict an outcome, or tell anyone what to do
    C-NAME     every investigation it names must appear in the evidence it cites
    C-COVER    a sentence that compares investigations must cite evidence for each one compared
    C-NUM      every number in it must appear in the evidence it cites
    C-METHOD   it must not say an investigation ran tests or simulations unless its record or label says so
    C-QUOTE    text in quotation marks must appear word for word in the evidence it cites
    C-SUPPORT  its content words must be found in the evidence it cites
    C-MECH     a physical mechanism it names (radiative extinction, buoyancy…) must be mentioned in a PSI document passage it cites
    C-DUP      it must not repeat an earlier kept sentence
    C-GENERIC  it must say something specific (a number, an investigation, a material or quoted words) when another sentence does
    C-LINK     links, markup, code, emails and phone numbers must appear in the evidence it cites
    C-ANCHOR   (only when asked for) it must cite at least one evidence item of a given kind, e.g. a computed pattern
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.catalog import Catalog
from app.insights.frame import QuestionReader
from app.insights.library import Item
from app.nimbus.method import MODEL_CUE, NOT_A_MODEL, REAL_PLATFORMS

MAX_SENTENCES = 5
MAX_SENTENCE_CHARS = 360

CITE_MARK = re.compile(r"\s*\[\s*\d+(?:\s*[,;–-]\s*\d+)*\s*\]")
DOI = re.compile(r"\b10\.\d{4,9}/\S+")
MIXED_TOKEN = re.compile(r"\b[A-Za-z]+-?\d[\w-]*|\b\d+[A-Za-z][\w-]*")      # PSI-25, FLEX-2, CO2, 21242A1, 3D
NUMBER = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w])\s*(%|percent\b|psi\b|atm\b|bar\b|mmhg\b|kpa\b)?", re.I)
NUMBER_WORDS = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
                "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
                "nineteen": 19, "twenty": 20}
# A number in a sentence may differ from the evidence only by the unit it states itself:
# "85%" for 0.85, or atm/bar/psi for a pressure. Nothing else is converted.
PRESSURE_FACTORS = (14.695949, 14.503774, 1 / 14.695949, 1 / 14.503774, 1.01325, 1 / 1.01325)
TOLERANCE = 0.015

QUOTED = re.compile(r"[\"“]([^\"”]{12,}?)[\"”]")
COMPARATIVE = re.compile(r"\b(both|each|all|same|similar(?:ly)?|differ\w*|whereas|while|unlike|compared|common|either|neither|than)\b", re.I)
FIRE_NOW = re.compile(
    r"\b(there is|there's|this is|that is|you have|we have|it is) (a |an )?(real |actual |active |developing )?(fire|emergency)\b"
    r"|\b(fire|smoke|combustion|flames?) (is|are) (occurring|happening|present|detected|developing|breaking out|burning now)\b"
    r"|\b(proves?|confirms?|establish(?:es)?|indicates?) (that )?(there is |a |an )?(fire|emergency)\b", re.I)
ADVICE = re.compile(r"\b(you|the crew|crew members?|astronauts?|mission control)\s+(should|must|need to|ought to|have to)\b"
                    r"|\b(evacuate|abandon (the )?(ship|station|module)|activate (the )?(alarm|suppression)|shut ?down|declare (an )?emergency)\b", re.I)
PREDICT = re.compile(r"\b(will|would|is going to|are going to)\s+(likely |probably |certainly |definitely )?"
                     r"(burn|ignite|spread|extinguish|fail|occur|happen|result in|cause|catch fire|grow|be safe|be dangerous)\b"
                     r"|\bpredict(s|ed|ing)?\b|\bforecast(s|ed)?\b", re.I)
EXPERIMENT_CLAIM = re.compile(r"\b(experimental(?:ly)?|experiments?|physical tests?|flight tests?|ran (?:its |their )?(?:own )?(?:physical )?tests?"
                              r"|flown|flew|(?:was|were) flown)\b", re.I)
SIMULATION_CLAIM = re.compile(r"\b(simulations?|simulated|simulate|CFD|numerical(?:ly)?|computer model(?:l?ing|s)?|model(?:l?ed|l?ing)|computational)\b", re.I)
UNSAFE = re.compile(r"(https?://\S+|www\.\S+|\]\(|!\[|<\s*/?\s*[a-z][^>]*>|javascript:|data:text|```|\brm -rf\b|\bsudo\b|\bcurl\s+http)", re.I)
EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,2}[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)")
ROMAN_NAME = re.compile(r"\b[A-Za-z]{3,}-(?:I{1,3}V?|IV|V|VI{1,3}|\d)\b")
STOP = frozenset("""about above after again against also among another because been before being below between both cannot could does doing
down during each either else even ever every from further have having here however into itself just least less like made make many
might more most much must near never only other others otherwise over same several shall should since some such than that their theirs
them then there therefore these they this those through thus under until upon very were what when where whether which while whom whose
will with within without would your investigation investigations study studies research data dashboard psi nasa record records
listed lists list found show shows shown showed state states stated given gives give includes include included including used uses use
using also called called named name names via per""".split())


@dataclass
class Removed:
    text: str
    cites: list[int]
    rules: list[str]
    reason: str


@dataclass
class Verification:
    kept: list[dict] = field(default_factory=list)          # {"text", "cites": [evidence numbers]}
    removed: list[Removed] = field(default_factory=list)
    checked: int = 0
    truncated: int = 0                                       # sentences past the maximum, not checked


def strip_cites(text: str) -> str:
    return CITE_MARK.sub("", text or "").strip()


def stem_key(word: str) -> str:
    w = word.lower()
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ied", "ed", "es", "s", "ly"):
        if len(w) > len(suffix) + 3 and w.endswith(suffix):
            w = w[: -len(suffix)]
            break
    return w[:6]


def content_keys(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z]{4,}", MIXED_TOKEN.sub(" ", text))
    return [stem_key(w) for w in words if w.lower() not in STOP]


def numbers_in(text: str) -> list[tuple[float, str | None]]:
    """(value, unit the text gives it) for every number; number words (two…twenty) have no unit."""
    cleaned = MIXED_TOKEN.sub(" ", DOI.sub(" ", text))
    out = [(float(m.group(1).replace(",", "")), (m.group(2) or "").lower() or None) for m in NUMBER.finditer(cleaned)]
    out += [(float(v), None) for w, v in NUMBER_WORDS.items() if re.search(rf"\b{w}\b", cleaned, re.I)]
    return out


def _decimals(s: float) -> int:
    text = f"{s:.6f}".rstrip("0")
    return len(text.split(".")[1]) if "." in text else 0


def number_supported(s: float, unit: str | None, evidence: list[float]) -> bool:
    d = _decimals(s)
    close = lambda y: bool(y) and (round(y, d) == s or abs(s - y) / abs(y) <= TOLERANCE)  # noqa: E731
    for x in evidence:
        if x == s or round(x, d) == s:
            return True
        if unit in ("%", "percent") and x <= 1 and close(x * 100):             # "85%" for 0.85
            return True
        if unit is None and s <= 1 and x > 1 and close(x / 100):               # "0.85" for "85%"
            return True
        if unit in ("psi", "atm", "bar", "kpa", "mmhg") and any(close(x * k) for k in PRESSURE_FACTORS):
            return True
    return False


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


class Checker:
    def __init__(self, catalog: Catalog, reader: QuestionReader) -> None:
        self.catalog = catalog
        self.reader = reader

    # -------------------------------------------------------------- helpers
    def _named(self, text: str) -> list[str]:
        ids, _ = self.reader._investigations(text, groups=False)
        return ids

    def _evidence_mentions(self, psi_id: str, cited: list[Item]) -> bool:
        return any(i.psi == psi_id or psi_id in self._named(i.text) for i in cited)

    # -------------------------------------------------------------- the rules
    def c_scope(self, text: str) -> str | None:
        if FIRE_NOW.search(text):
            return "says a fire is occurring; SI Insights never declares one"
        if ADVICE.search(text):
            return "tells someone what to do; SI Insights gives research context, not instructions"
        if PREDICT.search(text):
            return "predicts an outcome; SI Insights only reports what PSI's data shows"
        return None

    def c_name(self, text: str, cited: list[Item]) -> str | None:
        joined = " ".join(i.text for i in cited)
        for m in re.finditer(r"\bPSI-(\d+)\b", text):
            if f"PSI-{m.group(1)}" not in joined and not self._evidence_mentions(f"PSI-{m.group(1)}", cited):
                return f"names PSI-{m.group(1)}, which isn't in the evidence it cites"
        for psi_id in self._named(text):
            if not self._evidence_mentions(psi_id, cited):
                return f"names {self.reader.names.get(psi_id, psi_id)}, but the evidence it cites isn't about it"
        known = {a.lower() for a in self.reader.aliases}
        for m in ROMAN_NAME.finditer(text):
            token = m.group(0)
            if token.lower() not in known and _norm(token) not in _norm(joined):
                return f"names \"{token}\", which isn't an investigation in the evidence"
        return None

    def c_cover(self, text: str, cited: list[Item], frame) -> str | None:
        """A comparison must be backed by evidence about each investigation the question compares."""
        if frame is None or len(frame.psi_ids) < 2 or not COMPARATIVE.search(text):
            return None
        missing = [i for i in frame.psi_ids[:3] if not self._evidence_mentions(i, cited)]
        if missing:
            names = ", ".join(self.reader.names.get(i, i) for i in missing)
            return f"compares investigations, but doesn't cite any evidence about {names}"
        return None

    def c_num(self, text: str, cited: list[Item], computed_pool: list[float] | None = None) -> str | None:
        """Numbers must come from the cited evidence, or from a count or range that code itself computed for this question."""
        evidence = [x for i in cited for x, _ in numbers_in(i.text)] + (computed_pool or [])
        for s, unit in numbers_in(text):
            if not number_supported(s, unit, evidence):
                shown = f"{s:g}"
                return f"the number {shown} isn't in the evidence it cites"
        return None

    def c_link(self, text: str, cited: list[Item]) -> str | None:
        """The answer is shown as plain text, but a link, markup or command in it is still never something SI may add on its own."""
        joined = " ".join(i.text for i in cited)
        for m in UNSAFE.finditer(text):
            token = m.group(0)
            if token.lower().startswith(("http", "www")) and token.rstrip(".,;)") in joined:
                continue                                          # a link that really is in the cited PSI text
            return "contains a link, markup or code that the evidence it cites does not"
        for rx in (EMAIL, PHONE):
            m = rx.search(text)
            if m and m.group(0) not in joined:
                return "contains an email address or phone number that isn't in the evidence it cites"
        return None

    def c_method(self, text: str, cited: list[Item]) -> str | None:
        exp, sim = EXPERIMENT_CLAIM.search(text), SIMULATION_CLAIM.search(NOT_A_MODEL.sub(" ", text))
        if not (exp or sim):
            return None
        subjects = self._named(text) or sorted({i.psi for i in cited if i.psi in self.reader.names})[:1]
        for psi_id in subjects:
            inv = self.catalog.get(psi_id)
            checked = inv["method"]["status"] in ("verified", "team-confirmed")
            flag = inv["method"].get("flag", "") if checked else ""
            kinds = {"experimental", "simulation"} if flag == "both" else {flag}
            texts = " ".join(i.text for i in cited if i.psi == psi_id and i.kind in "RDP")
            flown = inv["project_type"] == "Microgravity" and bool(REAL_PLATFORMS.search(inv["platform"] or ""))
            if exp and not (flown or "experimental" in kinds):
                return (f"says {inv['name']} was experimental, but it is a {inv['project_type']} investigation and its method "
                        f"label {'is ' + inv['method']['flag'] if checked else 'is not confirmed'}")
            if sim and not ("simulation" in kinds or MODEL_CUE.search(NOT_A_MODEL.sub(" ", texts))):
                return f"says {inv['name']} used simulation, but neither its label nor the evidence it cites says so"
        return None

    def c_mech(self, text: str, cited: list[Item]) -> str | None:
        """Textbook physics never enters an answer on its own: a mechanism is named only if a cited PSI passage names it too."""
        passages = _norm(" ".join(i.text for i in cited if i.kind in "DPRA"))
        for term in self.catalog.vocabulary.get("mechanisms", []):
            if re.search(rf"(?<![A-Za-z]){re.escape(term)}(?![A-Za-z])", text, re.I) and _norm(term) not in passages:
                return f"names the mechanism \"{term}\", but no PSI passage it cites mentions it"
        return None

    def c_quote(self, text: str, cited: list[Item]) -> str | None:
        joined = _norm(" ".join(i.text for i in cited))
        for m in QUOTED.finditer(text):
            for part in re.split(r"…|\.\.\.", m.group(1)):
                if len(part.split()) >= 3 and _norm(part) not in joined:
                    return "has quoted text that isn't word for word in the evidence it cites"
        return None

    def c_support(self, text: str, cited: list[Item]) -> str | None:
        keys = content_keys(text)
        if not keys:
            return None
        have = {k for i in cited for k in content_keys(i.text)} | {k for i in cited for k in (stem_key(w) for w in re.findall(r"[A-Za-z]{4,}", i.where))}
        missing = [k for k in dict.fromkeys(keys) if k not in have]
        allowed = int(0.5 * len(set(keys)))
        if len(missing) > allowed:
            return "uses words that aren't in the evidence it cites (not supported by its sources)"
        return None

    # -------------------------------------------------------------- one sentence, all sentences
    def check(self, text: str, cites: list[int], evidence: list[Item], frame=None, anchor_kind: str | None = None) -> list[tuple[str, str]]:
        """Every rule the sentence fails, as (rule, reason). Empty means it passes.

        `anchor_kind` switches on C-ANCHOR: the sentence must cite at least one evidence item of that kind."""
        valid = [c for c in dict.fromkeys(cites) if isinstance(c, int) and 1 <= c <= len(evidence)]
        if not cites or len(valid) != len(set(cites)):
            return [("C-CITE", "cites no evidence, or evidence that doesn't exist")]
        cited = [evidence[c - 1] for c in valid]
        failures = []
        pool = [x for i in evidence if i.kind == "C" for x, _ in numbers_in(i.text)]
        if anchor_kind and not any(i.kind == anchor_kind for i in cited):
            failures.append(("C-ANCHOR", "cites no computed pattern, so it doesn't explain what these tests show"))
        for rule, fn in (("C-SCOPE", self.c_scope), ("C-NAME", self.c_name), ("C-COVER", lambda t, c: self.c_cover(t, c, frame)),
                         ("C-NUM", lambda t, c: self.c_num(t, c, pool)), ("C-LINK", self.c_link), ("C-METHOD", self.c_method), ("C-MECH", self.c_mech), ("C-QUOTE", self.c_quote), ("C-SUPPORT", self.c_support)):
            reason = fn(text) if rule == "C-SCOPE" else fn(text, cited)
            if reason:
                failures.append((rule, reason))
        return failures

    def verify(self, sentences: list[dict], evidence: list[Item], frame=None, anchor_kind: str | None = None) -> Verification:
        result = Verification()
        for raw in sentences[:MAX_SENTENCES]:
            text = strip_cites(str(raw.get("text", "")))[:MAX_SENTENCE_CHARS].strip()
            cites = [c for c in (raw.get("cites") or []) if isinstance(c, int) and not isinstance(c, bool)]
            if not text:
                continue
            result.checked += 1
            failures = self.check(text, cites, evidence, frame, anchor_kind)
            if failures:
                result.removed.append(Removed(text, cites, [r for r, _ in failures], failures[0][1]))
            else:
                result.kept.append({"text": text, "cites": list(dict.fromkeys(cites))})
        self._tidy(result)
        result.truncated = max(0, len(sentences) - MAX_SENTENCES)
        return result

    # -------------------------------------------------------------- across sentences: repeats and filler
    def specific(self, text: str) -> bool:
        """A number, a named investigation, quoted words, or an upper-case term (PMMA, CO2, MSG) makes a sentence concrete."""
        return bool(numbers_in(text) or self._named(text) or QUOTED.search(text) or re.search(r"\bPSI-\d+\b|\b[A-Z][A-Za-z]*[A-Z0-9]{2,}\b", text))

    def _tidy(self, result: Verification) -> None:
        kept: list[dict] = []
        for s in result.kept:
            keys = set(content_keys(s["text"]))
            if any(keys and len(keys & set(content_keys(k["text"]))) / len(keys | set(content_keys(k["text"]))) >= 0.5 for k in kept):
                result.removed.append(Removed(s["text"], s["cites"], ["C-DUP"], "repeats an earlier sentence"))
            else:
                kept.append(s)
        concrete = [s for s in kept if self.specific(s["text"])]
        keep = concrete or kept[:1]                       # filler is dropped only when a concrete sentence is there; otherwise the first stays
        for s in kept:
            if s not in keep:
                result.removed.append(Removed(s["text"], s["cites"], ["C-GENERIC"], "says nothing specific: no number, investigation, material or quote"))
        result.kept = keep
