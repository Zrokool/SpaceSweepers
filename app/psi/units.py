"""Unit conversions, each one explicit and unit-tested. Canonical units: psi, mole fraction."""

PSI_PER = {"psi": 1.0, "bar": 14.503774, "atm": 14.695949, "mmhg": 0.01933678, "torr": 0.01933678,
           "kpa": 0.14503774}
FRACTION_PER = {"mole_fraction": 1.0, "percent": 0.01}
# Units that pass through unchanged (the variable's name carries the unit).
PASS_THROUGH = {"s", "k", "mg/s", "cm/s", "mm", "mm2/s", "mmhg", "count"}


def convert(value: float, unit: str, variable: str) -> float:
    """Convert `value` from `unit` to the canonical unit of `variable`."""
    u = unit.lower()
    if variable == "pressure_psi":
        if u not in PSI_PER:
            raise ValueError(f"no pressure conversion from {unit!r}")
        return value * PSI_PER[u]
    if variable.endswith("_fraction"):                     # oxygen, nitrogen, helium, CO2: all gas mole fractions
        if u not in FRACTION_PER:
            raise ValueError(f"no gas-fraction conversion from {unit!r}")
        return value * FRACTION_PER[u]
    if u in PASS_THROUGH:
        return value
    raise ValueError(f"no conversion from {unit!r} for {variable}")
