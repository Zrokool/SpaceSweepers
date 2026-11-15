"""Habitat atmosphere profiles from the challenge text, as boxes in (oxygen, pressure) space.

The challenge gives single numbers; the bands around them are our assumption, shown in the UI.
"""

HABITATS = {
    "iss": {"label": "ISS / spacecraft", "summary": "21% O₂ · 14.7 psi",
            "o2": [0.195, 0.235], "pressure_psi": [13.9, 15.2],
            "basis": "Earth-normal air, as on the ISS. The band is ISS's normal operating range (assumption)."},
    "moon": {"label": "Moon base / pressurized rover", "summary": "≥ 30% O₂ · ≤ 10.2 psi",
             "o2": [0.30, 1.0], "pressure_psi": [4.3, 10.2],
             "basis": "Challenge text: oxygen 30% or greater at 10.2 psi or less, between a spacesuit and Earth."},
    "eva": {"label": "Spacesuit (EVA)", "summary": "100% O₂ · 4.3 psi",
            "o2": [0.95, 1.0], "pressure_psi": [3.5, 5.0],
            "basis": "Challenge text: suits hold 100% oxygen at 4.3 psi. The band is our assumption."},
}
DEFAULT_HABITAT = "moon"


def in_box(habitat: dict, o2: float | None, pressure: float | None) -> bool:
    if o2 is None or pressure is None:
        return False
    return habitat["o2"][0] <= o2 <= habitat["o2"][1] and \
        habitat["pressure_psi"][0] <= pressure <= habitat["pressure_psi"][1]
