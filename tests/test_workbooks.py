"""PSI spreadsheet workbooks: login details are never stored, columns keep their place, and nothing is stored twice."""

import io
import json
import zipfile
from pathlib import Path

from app.psi import documents, workbooks

DATA = Path(__file__).resolve().parent.parent / "data"


def tiny_xlsx(rows: dict[int, dict[str, str]]) -> bytes:
    """A real .xlsx with inline strings, one sheet. `rows` maps a row number to {cell reference: text}."""
    sheet = "".join(f'<row r="{r}">' + "".join(f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>' for ref, v in cells.items()) + "</row>"
                    for r, cells in rows.items())
    parts = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>',
        "xl/workbook.xml": '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="S1" sheetId="1" r:id="rId1"/></sheets></workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/worksheets/sheet1.xml": f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{sheet}</sheetData></worksheet>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, xml in parts.items():
            z.writestr(name, xml)
    return buf.getvalue()


# ------------------------------------------------------------------ login details
def test_login_details_are_removed_and_ordinary_text_is_not():
    first, second = "Zx9Sec" + "ret!77", "Tr0ub" + "4dor&3"           # fake values, built at run time so no sample login ever appears in the repository
    text = f"Run notes. svc1abc; {first} and ops\\acct2; {second} were used. Tests at 21%; 3 atm; Table 3; Figure 12; PSI-25; BASS-II."
    out = documents.redact(text)
    assert first not in out and second not in out and out.count("[credential removed]") == 2
    assert "Tests at 21%; 3 atm; Table 3; Figure 12; PSI-25; BASS-II." in out            # semicolons in normal prose are untouched


def test_no_login_details_anywhere_in_the_stored_snapshot():
    hits = []
    for f in (DATA / "snapshot").rglob("*"):
        if f.is_file() and f.suffix in (".txt", ".csv", ".json"):
            if documents.CREDENTIAL.search(f.read_text(encoding="utf-8", errors="replace")):
                hits.append(f.name)
    assert hits == []


def test_the_library_never_holds_login_details(catalog_and_library):
    _, lib = catalog_and_library
    assert [i.id for i in lib.items.values() if documents.CREDENTIAL.search(i.text)] == []


def test_the_plan_matrix_is_listed_as_not_read_with_its_reason():
    manifest = json.loads((DATA / "snapshot" / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["investigations"]["PSI-26"]
    book = next(w for w in entry["workbooks"] if w["file"].endswith("Planned_Test Matrix.xlsx"))
    assert book["handling"] == "not stored" and book["reason"].startswith("a test plan")
    assert not any(d["file"].endswith("Planned_Test Matrix.xlsx") for d in entry["documents"])           # not a document, so never "unread"
    assert not list((DATA / "snapshot" / "docs" / "PSI-26").glob("*Planned*"))


def test_a_file_on_the_not_read_list_is_skipped_with_its_reason():
    record = {"added": [{"file_name": "PSI-26_Science Documents_Planned_Test Matrix.xlsx", "file_size": 20976,
                         "remote_path": "psi-repo-prod/investigations/PSI-26/files/Science Documents/PSI-26_Planned.xlsx"}]}
    take, skip = documents.selection(record, workbooks.not_read())
    assert take == [] and "login details" in skip[0]["reason"]


# ------------------------------------------------------------------ columns keep their place
def test_a_blank_cell_between_values_does_not_move_later_columns():
    data = tiny_xlsx({1: {"A1": "id", "B1": "k_hot", "C1": "k_cool", "D1": "pressure"}, 2: {"A2": "1206", "C2": "0.385", "D2": "1"}})   # B2 is empty
    (name, grid), = documents.read_sheets(data)
    assert grid[2] == {1: "1206", 3: "0.385", 4: "1"}                                   # k_cool stays in column C, not B
    text = documents.extract_xlsx(data).text.split("\n")
    assert text[-1].split("\t") == ["1206", "", "0.385", "1"]                          # the chat's text keeps the blank too


def test_the_real_cfi_workbook_keeps_its_columns():
    cached = DATA.parent / ".cache" / "psi-docs" / "PSI-39" / "PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx"
    if not cached.exists():
        return                                                                          # the cache is local only
    sheets = dict(documents.read_sheets(cached.read_bytes()))
    header = sheets["DATA"][min(sheets["DATA"])]
    gappy = next(c for r, c in sheets["DATA"].items() if r != min(sheets["DATA"]) and 8 in c and 4 not in c)    # a test with no k_hot value
    assert header[4].strip().startswith("khot") and header[8] == "Reignitions" and 4 not in gappy and 8 in gappy


# ------------------------------------------------------------------ one canonical table per workbook
from app.psi import harmonise  # noqa: E402


def multi_xlsx(sheets: dict[str, dict[int, dict[str, str]]]) -> bytes:
    """A real .xlsx with several inline-string sheets: {sheet name: {row number: {cell reference: text}}}."""
    names, rels, parts = [], [], {}
    for n, (name, rows) in enumerate(sheets.items(), 1):
        body = "".join(f'<row r="{r}">' + "".join(f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>' for ref, v in cells.items()) + "</row>" for r, cells in rows.items())
        parts[f"xl/worksheets/sheet{n}.xml"] = f'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{body}</sheetData></worksheet>'
        names.append(f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>')
        rels.append(f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml"/>')
    parts["xl/workbook.xml"] = ('<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
                                + "".join(names) + "</sheets></workbook>")
    parts["xl/_rels/workbook.xml.rels"] = '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels) + "</Relationships>"
    parts["[Content_Types].xml"] = '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, xml in parts.items():
            z.writestr(name, xml)
    return buf.getvalue()


RECIPE = {"key": "Test", "key_pattern": r"^\d+[A-Za-z]?$", "sheets": ["Master", "Results"]}


def two_sheets() -> bytes:
    return multi_xlsx({
        "Master": {1: {"A1": "Test", "B1": "Pressure", "C1": "Fuel"}, 2: {"A2": "1", "B2": "1 atm", "C2": "heptane"}, 3: {"A3": "2A ", "B3": "3 atm", "C3": "heptane"},
                   4: {"A4": "SETUP", "B4": "x"}, 5: {"A5": "3", "B5": "5 atm"}},                   # test 3 has no fuel cell; SETUP is not a test
        "Results": {2: {"A2": "Test", "C2": "Pressure"}, 3: {"A3": "1", "C3": "1.0"}, 4: {"A4": "2A", "B4": "9", "C4": "3.0"}, 5: {"A5": "99", "B5": "8"}},
    })


def test_the_join_keeps_every_row_places_columns_and_reports_what_did_not_match():
    columns, rows, report = workbooks.build_table(RECIPE, two_sheets())
    assert columns == ["Test", "Pressure", "Fuel", "Pressure [Results]"] and len(rows) == 3         # SETUP is not a test; a clashing name is tagged with its sheet
    assert rows[1]["Test"] == "2A" and rows[1]["Pressure [Results]"] == "3.0" and rows[2].get("Fuel") is None     # a key with a letter matches after trimming
    assert report["unmatched"]["Results"] == ["99"] and report["missing"]["Results"] == ["3"] and report["rows"] == 3


def test_a_repeated_key_is_never_collapsed():
    data = multi_xlsx({"Master": {1: {"A1": "Test", "B1": "Time"}, 2: {"A2": "24", "B2": "17:34"}, 3: {"A3": "24", "B3": "17:40"}, 4: {"A4": "25", "B4": "18:00"}}})
    _, rows, report = workbooks.build_table({"key": "Test", "sheets": ["Master"]}, data)
    assert [r["Time"] for r in rows] == ["17:34", "17:40", "18:00"] and report["repeated_keys"] == ["24"]       # two real runs share number 24


def test_the_simulated_list_is_kept_exactly_as_written_in_blocks():
    data = multi_xlsx({"S": {1: {"B1": "Fuel", "C1": "do (mm)", "D1": "XN2"}, 2: {"B2": "n-heptane", "C2": "0.5", "D2": "74", "I2": "Stable_Cool", "K2": "Fig. 1"},
                             4: {"B4": "Fuel", "C4": "P (atm)", "D4": "XN2"}, 5: {"B5": "n-dodecane", "C5": "0.5 - 5.0", "D5": "0.79", "I5": "Other_Run"}}})
    columns, rows = workbooks.build_simulations({"sheet": "S"}, data)
    assert rows[0]["XN2"] == "74" and rows[1]["XN2"] == "0.79" and rows[1]["P (atm)"] == "0.5 - 5.0"          # ranges and mixed units are not converted
    assert rows[0]["Data File"] == "Stable_Cool" and rows[0]["Figure"] == "Fig. 1" and {"do (mm)", "P (atm)", "Data File", "Figure"} <= set(columns)


def test_a_count_can_be_read_as_a_category():
    spec = {"kind": "category_from_number", "threshold": 0, "above": "reignited", "otherwise": "no_reignition"}
    assert harmonise.parse_value("outcome", spec, "3").value == "reignited" and harmonise.parse_value("outcome", spec, "0").value == "no_reignition"
    blank = harmonise.parse_value("outcome", spec, "")
    assert blank.value is None and blank.flag == "missing"                                                   # a blank is never "no reignition"


def test_apply_writes_one_table_supersedes_the_csv_and_drops_the_text(tmp_path):
    snapshot, docs = tmp_path / "snapshot", tmp_path / "docs"
    (docs / "PSI-1").mkdir(parents=True)
    (docs / "PSI-1" / "wb.xlsx").write_bytes(two_sheets())
    (snapshot / "docs" / "PSI-1").mkdir(parents=True)
    (snapshot / "docs" / "PSI-1" / "wb.xlsx.txt").write_text("workbook text", encoding="utf-8")
    recipes = tmp_path / "workbooks.yaml"
    recipes.write_text("tables:\n  - {name: 'PSI-1_Workbook table_T.csv', investigation: PSI-1, workbook: wb.xlsx, key: Test, key_pattern: '^\\d+[A-Za-z]?$', "
                       "sheets: [Master, Results], supersedes: old.csv}\n", encoding="utf-8")
    entry = {"tables": [{"file": "tables/PSI-1/old.csv", "bytes": 1, "sha256": "x"}],
             "documents": [{"file": "wb.xlsx", "status": "read", "text_file": "docs/PSI-1/wb.xlsx.txt", "pages": 2, "characters": 13}]}
    messages = workbooks.apply("PSI-1", entry, docs, snapshot, recipes)
    new = next(t for t in entry["tables"] if t["file"].endswith("T.csv"))
    assert "3 tests" in messages[0] and new["source"] == "workbook" and new["join"]["rows"] == 3 and (snapshot / new["file"]).exists()
    assert next(t for t in entry["tables"] if t["file"].endswith("old.csv"))["superseded_by"] == new["file"]
    assert entry["documents"] == [] and not (snapshot / "docs/PSI-1/wb.xlsx.txt").exists()                  # no longer a document: nothing to read or index twice
    assert entry["workbooks"][0]["handling"] == "converted to a table" and "one stored copy" in entry["workbooks"][0]["reason"]


def test_the_real_workbooks_give_the_expected_tables():
    cache = DATA.parent / ".cache" / "psi-docs"
    cfi = cache / "PSI-39" / "PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx"
    if not cfi.exists():
        return                                                                                        # the cache is local only
    recipe = next(r for r in workbooks.load()["tables"] if r["investigation"] == "PSI-39")
    columns, rows, report = workbooks.build_table(recipe, cfi.read_bytes())
    assert len(rows) == 227 and report["unmatched"] == {"DATA": [], "Igniter": [], "Comments": []} and {"Reignitions", "Dext, hot ( mm )", "Comments"} <= set(columns)
    bass = next(r for r in workbooks.load()["tables"] if r["investigation"] == "PSI-26")
    _, brows, breport = workbooks.build_table(bass, (cache / "PSI-26" / bass["workbook"]).read_bytes())
    assert len(brows) == 121 and breport["repeated_keys"] == ["24", "85", "89", "90", "91"]            # five as-run numbers are shared by two real runs


def test_a_handled_workbook_is_not_counted_as_an_unread_document():
    take, skip = documents.selection({"added": [
        {"file_name": "PSI-26_Science Documents_Planned_Test Matrix.xlsx", "file_size": 100, "remote_path": "a/b/c/d/Science Documents/x"},
        {"file_name": "big.pdf", "file_size": 9_000_000, "remote_path": "a/b/c/d/Reports/x"}]}, workbooks.not_read())
    docs, books = documents.split_handled([{**s, "status": f"not read: {s['reason']}"} for s in skip])
    assert [d["file"] for d in docs] == ["big.pdf"]                                         # genuinely unread: over the size cap
    assert books[0]["handling"] == "not stored" and "login details" in books[0]["reason"]


def test_a_snapshot_made_before_the_list_existed_is_tidied(tmp_path):
    entry = {"tables": [], "documents": [{"file": "PSI-26_Science Documents_Planned_Test Matrix.xlsx", "folder": "Science Documents", "bytes": 5, "status": "read", "text_file": "docs/PSI-26/p.txt"},
                                         {"file": "other.pdf", "folder": "Reports", "bytes": 5, "status": "read", "text_file": None}]}
    (tmp_path / "docs" / "PSI-26").mkdir(parents=True)
    (tmp_path / "docs" / "PSI-26" / "p.txt").write_text("plan", encoding="utf-8")
    workbooks.tidy_not_read("PSI-26", entry, tmp_path)
    assert [d["file"] for d in entry["documents"]] == ["other.pdf"] and entry["workbooks"][0]["handling"] == "not stored" and not (tmp_path / "docs/PSI-26/p.txt").exists()


def test_sync_calls_the_converter(tmp_path):
    source = (DATA.parent / "app" / "psi" / "sync.py").read_text(encoding="utf-8")
    assert "workbooks.apply(psi_id, entry, docs_dir, out_dir)" in source and "documents.split_handled(entries)" in source
