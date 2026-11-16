"""Findings from the security scans, fixed and kept fixed: no SHA-1 in the app, and Word or Excel XML is parsed only without a DTD."""

import io
import re
import zipfile
from pathlib import Path

from app.psi import documents

APP = Path(__file__).resolve().parent.parent / "app"
BILLION_LAUGHS = (b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>'
                  b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>&lol2;</w:t></w:r></w:p></w:body></w:document>')
WORD = (b'<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        b'<w:body><w:p><w:r><w:t>Flame spread was measured.</w:t></w:r></w:p></w:body></w:document>')


def zipped(parts: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in parts.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_an_ordinary_word_file_is_still_read():
    got = documents.extract_docx(zipped({"word/document.xml": WORD}))
    assert got.text == "Flame spread was measured." and got.status == "read"


def test_a_word_file_that_declares_a_dtd_is_refused_not_expanded():
    got = documents.extract_docx(zipped({"word/document.xml": BILLION_LAUGHS}))
    assert got.text == "" and got.status.startswith("not read") and "DTD" in got.status


def test_a_dtd_hidden_in_utf16_is_refused_too():
    hidden = b"\xff\xfe" + BILLION_LAUGHS.decode().encode("utf-16-le")
    got = documents.extract_docx(zipped({"word/document.xml": hidden}))
    assert got.text == "" and got.status.startswith("not read")


def test_an_excel_file_that_declares_entities_is_refused():
    parts = {"xl/workbook.xml": BILLION_LAUGHS, "xl/_rels/workbook.xml.rels": b"<Relationships/>"}
    got = documents.extract_xlsx(zipped(parts))
    assert got.text == "" and got.status.startswith("not read")


def test_the_app_no_longer_uses_sha1_for_its_short_labels():
    assert not [p.name for p in APP.rglob("*.py") if re.search(r"hashlib\.sha1|hashlib\.md5", p.read_text(encoding="utf-8"))]
    from app.insights import pipeline  # noqa: F401  (imports cleanly)
