"""The method note at the foot of every page quotes numbers that the calculations use. They must not drift from the code."""

import re
from pathlib import Path

from app.analysis import rank, sweeper
from app.analysis.habitats import HABITATS

HTML = (Path(__file__).resolve().parent.parent / "static" / "index.html").read_text(encoding="utf-8")
NOTE = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", HTML[HTML.index('class="method-note"'):]))


def test_the_note_quotes_the_rank_constants_as_they_are_in_the_code():
    w = rank.DEFAULT_WEIGHTS
    assert f"condition match {w['proximity']}, fuel {w['fuel']}, pillar evidence {w['pillar']} and data richness {w['data']}" in NOTE
    assert f"within {rank.NEAR_O2:g} oxygen mole fraction and {rank.NEAR_PSI:g} psi" in NOTE
    assert f"{rank.PROXIMITY_FULL} such tests give full marks" in NOTE
    f = rank.FUEL_SCORE
    assert f"solid {f['solid']}, liquid {f['liquid']} and gas {f['gas']}" in NOTE


def test_the_note_quotes_the_flame_sweeper_rules_as_they_are_in_the_code():
    assert f"cells of {sweeper.O2_STEP:g} oxygen mole fraction by {sweeper.P_STEP:g} atm" in NOTE
    assert f"{sweeper.FOLDS}-fold cross-validation" in NOTE
    assert f"by at least {sweeper.MIN_SKILL_GAIN * 100:.0f} percentage points with an AUC of at least {sweeper.MIN_AUC:.2f}" in NOTE


def test_the_note_names_the_habitat_atmospheres_the_code_uses_and_the_bands_come_from_the_same_table():
    assert "ISS 21% O₂ at 14.7 psi" in NOTE and "spacesuit 100% O₂ at 4.3 psi" in NOTE
    assert "at least 30% O₂ at no more than 10.2 psi" in NOTE
    assert HABITATS["moon"]["o2"][0] == 0.30 and HABITATS["moon"]["pressure_psi"][1] == 10.2     # the figures the note quotes
    assert 'id="method-habitats"' in HTML and "state.meta.habitats" in (Path(__file__).resolve().parent.parent / "static" / "js" / "app.js").read_text(encoding="utf-8")
