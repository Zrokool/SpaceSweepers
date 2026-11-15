"""Harmonising test tables: nothing is silently cleaned, and every odd value is flagged."""

import pytest
import yaml

from app.psi.harmonise import harmonise_table, load_mappings, parse_number
from app.psi.units import convert
from tests.fakes import TABLE_CSV, TABLE_NAME

MAPPING = {
    "investigation": "PSI-900", "file": TABLE_NAME, "test_id": "Test", "fuel_class": "solid", "o2_role": "ambient",
    "columns": {
        "fuel": {"column": "Fuel", "kind": "text"},
        "o2_fraction": {"column": "XO2", "kind": "number", "unit": "mole_fraction", "min": 0, "max": 1},
        "pressure_psi": {"column": "P (atm)", "kind": "number", "unit": "atm", "min": 0.5, "max": 150},
        "co_ppm": {"column": "CO (ppm)", "kind": "number", "unit": "s", "min": 0, "max": 1e5},
        "outcome": {"column": "Ignited", "kind": "category", "values": {"yes": "ignited", "no": "no_ignition", "flash": "flash"}},
        "missing_col": {"column": "Not In Table", "kind": "number", "unit": "s"},
    },
}


@pytest.mark.parametrize("raw,expected", [
    ("0.21", (0.21, "ok", None, None)), ("~21", (21.0, "approx", None, None)), ("21%", (21.0, "ok", None, None)),
    ("21.5 - 21.7", (21.6, "range", 21.5, 21.7)), ("0.17; 0.21; 0.25", (None, "multi", None, None)),
    ("none", (None, "missing", None, None)), ("", (None, "missing", None, None)), ("-", (None, "missing", None, None)),
    ("-1", (-1.0, "ok", None, None)), ("abc", (None, "unparsed", None, None)), ("1e-3", (0.001, "ok", None, None)),
])
def test_parse_number(raw, expected):
    value, flag, lo, hi = parse_number(raw)
    assert (None if value is None else round(value, 6), flag, lo, hi) == expected


def test_unit_conversions():
    assert convert(1, "atm", "pressure_psi") == pytest.approx(14.696, abs=1e-3)
    assert convert(1.1033, "bar", "pressure_psi") == pytest.approx(16.002, abs=1e-3)
    assert convert(760, "mmHg", "pressure_psi") == pytest.approx(14.696, abs=1e-2)
    assert convert(30, "percent", "o2_fraction") == pytest.approx(0.30)
    with pytest.raises(ValueError):
        convert(1, "furlongs", "pressure_psi")


def test_table_keeps_raw_text_and_flags_every_oddity():
    result = harmonise_table(TABLE_CSV, MAPPING, TABLE_NAME)
    tests = {t["test_id"]: t for t in result["tests"]}
    assert list(tests) == ["T1", "T2", "T3", "T4", "T5"]          # the blank row and the note row aren't tests
    assert result["coverage"]["blank_rows"] == 1 and result["coverage"]["note_rows"] == 1
    assert result["coverage"]["columns_missing"] == ["Not In Table"]
    t2, t3, t4, t5 = (tests[k]["values"] for k in ("T2", "T3", "T4", "T5"))
    assert (t2["o2_fraction"]["raw"], t2["o2_fraction"]["value"], t2["o2_fraction"]["flag"]) == ("~0.30", 0.3, "approx")
    assert t2["pressure_psi"]["value"] == pytest.approx(10.14, abs=0.01) and t2["pressure_psi"]["unit"] == "psi"
    assert t2["co_ppm"]["flag"] == "missing" and t2["outcome"]["value"] == "ignited"   # "yes" in lower case
    assert t3["o2_fraction"]["flag"] == "implausible"          # 21.6 written as a percent in a mole-fraction column
    assert (t3["o2_fraction"]["lo"], t3["o2_fraction"]["hi"]) == (21.5, 21.7)
    assert t3["co_ppm"]["flag"] == "implausible" and t3["co_ppm"]["raw"] == "-1"      # negative CO reading kept, flagged
    assert t4["o2_fraction"]["flag"] == "multi" and t4["o2_fraction"]["value"] is None
    assert t5["co_ppm"]["flag"] == "unparsed" and t5["co_ppm"]["raw"] == "abc"
    assert tests["T1"]["row"] == 2 and tests["T5"]["row"] == 8  # row numbers point back into the source file


def test_mapping_with_bare_yes_no_keys_is_rejected(tmp_path):
    """YAML reads bare yes/no as booleans; such a mapping would silently match nothing."""
    (tmp_path / "PSI-900.yaml").write_text(yaml.safe_dump({"investigation": "PSI-900", "tables": [{
        "file": "t.csv", "test_id": "Test", "columns": {"outcome": {"column": "Ignited", "kind": "category",
                                                                   "values": {True: "ignited", False: "no_ignition"}}}}]}))
    with pytest.raises(ValueError, match="quote them"):
        load_mappings(tmp_path)
