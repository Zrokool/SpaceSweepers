"""PSI documents: which ones the dashboard reads, and how their text is extracted.

Read: files in the "Reports" and "Science Documents" folders, plus any file named
like a ReadMe, as PDF, Word (.docx), Excel (.xlsx), text or CSV, up to 5 MB each.
Never read: Raw Data, video, images, and anything larger or in another format.
Those are listed in the manifest as "not read", with the reason.

Text is kept as the document says it, page by page, except that email addresses,
phone numbers and login details are removed (they are never stored).
"""

from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree  # nosec B405 - only parsed through _parse_xml below, which refuses DTDs

from pypdf import PdfReader
from pypdf.errors import PdfReadError

DOC_FOLDERS = ("Reports", "Science Documents")
README_NAME = re.compile(r"read ?me", re.I)
DOC_SUFFIXES = (".pdf", ".docx", ".xlsx", ".txt", ".csv")
MAX_DOC_BYTES = 5_000_000
MAX_UNZIPPED_BYTES = 60_000_000      # a Word or Excel file that unpacks to more than this is refused
MAX_SHEET_ROWS = 2_000               # rows kept per spreadsheet sheet

EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\d)")
PAGE_MARK = "[[page {n}]]"


def folder_of(remote_path: str) -> str:
    parts = remote_path.split("/")
    return parts[4] if len(parts) > 5 else "(top level)"


def is_wanted(folder: str, name: str) -> bool:
    """Whether a file is a document the dashboard reads (before the size and type checks)."""
    return folder in DOC_FOLDERS or bool(README_NAME.search(name))


def selection(record: dict, not_read: dict[str, str] | None = None) -> tuple[list[dict], list[dict]]:
    """(documents to read, documents listed but not read), from a full PSI record's file list.

    `not_read` maps a file name (or its ending) to the reason it is deliberately left out (see data/workbooks.yaml)."""
    take, skip = [], []
    not_read = not_read or {}
    for f in (record.get("added") or []) + (record.get("modified") or []):
        name, size, folder = f.get("file_name") or "", f.get("file_size") or 0, folder_of(f.get("remote_path", ""))
        if not is_wanted(folder, name):
            continue
        item = {"file": name, "folder": folder, "bytes": size}
        if not name.lower().endswith(DOC_SUFFIXES):
            skip.append({**item, "reason": f"{Path(name).suffix or 'this'} files aren't read (only PDF, Word .docx, Excel .xlsx, text, CSV)"})
        elif reason := next((why for key, why in not_read.items() if name.endswith(key)), None):
            skip.append({**item, "reason": reason, "handled": True})      # left out on purpose, not unread: recorded as a workbook
        elif size > MAX_DOC_BYTES:
            skip.append({**item, "reason": f"larger than {MAX_DOC_BYTES // 1_000_000} MB"})
        else:
            take.append(item)
    return take, skip


# A user name and a password-like token written as "name; token" (the token mixes letters and digits and is 7+ characters).
# Nothing secret is listed anywhere: this is a pattern, so no credential is ever stored, not even in a block list.
CREDENTIAL = re.compile(r"\b[A-Za-z][A-Za-z0-9\\]{3,};\s+[!$#]?(?=[A-Za-z0-9!$#]*\d)(?=[A-Za-z0-9!$#]*[A-Za-z])[A-Za-z0-9!$#]{7,}")


def split_handled(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """(documents, workbooks): a workbook that was converted to a table or left out on purpose is recorded apart from the
    documents, so "not read" always means a file we could not read (too large, an unreadable format, a failed download)."""
    return ([e for e in entries if not e.get("handled")],
            [{"file": e["file"], "folder": e.get("folder"), "bytes": e.get("bytes"), "handling": "not stored", "reason": e.get("reason")}
             for e in entries if e.get("handled")])


def redact(text: str) -> str:
    """Remove email addresses, phone numbers and login details."""
    return CREDENTIAL.sub("[credential removed]", PHONE.sub("[phone removed]", EMAIL.sub("[email removed]", text)))


@dataclass
class Extracted:
    text: str        # with [[page n]] markers for PDFs
    pages: int       # pages (PDF), sheets (Excel) or 1
    status: str      # "read", or why no text came out


def _zip_member(z: zipfile.ZipFile, name: str) -> bytes | None:
    try:
        info = z.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_UNZIPPED_BYTES:
        raise ValueError(f"{name} unpacks to {info.file_size} bytes")
    return z.read(name)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _parse_xml(data: bytes) -> ElementTree.Element:
    """Parse one XML part of a Word or Excel file.

    These parts never need a DTD, and a DTD or entity declaration is how XML entity-expansion attacks are built, so a part that
    declares one is refused. Parts are UTF-8; a UTF-16 byte-order mark would hide the markers from this check, so it is refused too.
    """
    if data[:2] in (b"\xff\xfe", b"\xfe\xff") or b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ElementTree.ParseError("the XML part declares a DTD or is not UTF-8, which Word and Excel files do not need")
    return ElementTree.fromstring(data)  # nosec B314 - DTDs and entities are refused above


def extract_pdf(data: bytes) -> Extracted:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            return Extracted("", 0, "not read: the PDF is password-protected")
        parts = []
        for n, page in enumerate(reader.pages, 1):
            try:
                text = page.extract_text() or ""
            except Exception:  # noqa: BLE001 - a single bad page shouldn't lose the rest
                text = ""
            parts.append(PAGE_MARK.format(n=n) + "\n" + text.strip())
        pages = len(reader.pages)
    except (PdfReadError, ValueError, KeyError, OSError) as e:
        return Extracted("", 0, f"not read: the PDF couldn't be opened ({type(e).__name__})")
    text = "\n\n".join(parts)
    words = len(re.findall(r"[A-Za-z]{3,}", text))
    return Extracted(text, pages, "read" if words >= 20 else "no text found (probably a scanned PDF)")


def extract_docx(data: bytes) -> Extracted:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = _zip_member(z, "word/document.xml")
    except (zipfile.BadZipFile, ValueError) as e:
        return Extracted("", 0, f"not read: the Word file couldn't be opened ({e})")
    if xml is None:
        return Extracted("", 0, "not read: no document text inside the Word file")
    try:
        root = _parse_xml(xml)
    except ElementTree.ParseError as e:
        return Extracted("", 0, f"not read: the Word file's text couldn't be parsed ({e})")
    paragraphs = []
    for p in root.iter():
        if _local(p.tag) != "p":
            continue
        line = "".join(t.text or "" for t in p.iter() if _local(t.tag) == "t").strip()
        if line:
            paragraphs.append(line)
    text = "\n".join(paragraphs)
    return Extracted(text, 1, "read" if text.strip() else "no text found")


def _col_number(ref: str) -> int:
    """Column number of a cell reference: A1 -> 1, AB7 -> 28."""
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n


def read_sheets(data: bytes, max_rows: int = MAX_SHEET_ROWS) -> list[tuple[str, dict[int, dict[int, str]]]]:
    """Every sheet of an .xlsx as {row number: {column number: text}}, placed by each cell's own reference.

    An empty cell is simply absent in the file, so joining only the cells that exist would move every later value one
    column left. Placing by reference keeps each value in its true column. Raises ValueError for a file that isn't a workbook."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            shared_xml = _zip_member(z, "xl/sharedStrings.xml")
            workbook = _zip_member(z, "xl/workbook.xml")
            rels = _zip_member(z, "xl/_rels/workbook.xml.rels")
            shared = []
            if shared_xml:
                for si in _parse_xml(shared_xml):
                    shared.append("".join(t.text or "" for t in si.iter() if _local(t.tag) == "t"))
            targets = {}
            if rels:
                for rel in _parse_xml(rels):
                    targets[rel.get("Id")] = rel.get("Target", "").lstrip("/")
            sheets = []
            if workbook:
                for s in _parse_xml(workbook).iter():
                    if _local(s.tag) == "sheet":
                        rid = next((v for k, v in s.attrib.items() if k.endswith("}id")), None)
                        target = targets.get(rid, "")
                        sheets.append((s.get("name") or "Sheet", target if target.startswith("xl/") else f"xl/{target}"))
            out = []
            for name, path in sheets:
                xml = _zip_member(z, path)
                if xml is None:
                    continue
                grid: dict[int, dict[int, str]] = {}
                for row in _parse_xml(xml).iter():
                    if _local(row.tag) != "row":
                        continue
                    cells: dict[int, str] = {}
                    for position, c in enumerate(x for x in row if _local(x.tag) == "c"):
                        v = next((x.text for x in c if _local(x.tag) == "v"), None)
                        inline = "".join(t.text or "" for t in c.iter() if _local(t.tag) == "t")
                        if c.get("t") == "s" and v is not None and v.isdigit() and int(v) < len(shared):
                            value = shared[int(v)]
                        else:
                            value = inline or (v or "")
                        if value.strip():
                            cells[_col_number(c.get("r") or "A") if c.get("r") else position + 1] = value
                    if cells:
                        grid[int(row.get("r") or len(grid) + 1)] = cells
                        if len(grid) >= max_rows:
                            break
                out.append((name, grid))
            return out
    except (zipfile.BadZipFile, ElementTree.ParseError) as e:
        raise ValueError(f"the Excel file couldn't be opened ({e})") from None


def extract_xlsx(data: bytes) -> Extracted:
    try:
        sheets = read_sheets(data)
    except ValueError as e:
        return Extracted("", 0, f"not read: {e}")
    out = []
    for name, grid in sheets:
        out.append(f"[[sheet {name}]]")
        for _, cells in sorted(grid.items()):
            out.append("\t".join(cells.get(c, "") for c in range(1, max(cells) + 1)).rstrip())     # blanks keep their column
        if len(grid) >= MAX_SHEET_ROWS:
            out.append(f"[[sheet {name} cut after {MAX_SHEET_ROWS} rows]]")
    text = "\n".join(out)
    return Extracted(text, len(sheets), "read" if text.strip() else "no text found")


def extract_text(data: bytes) -> Extracted:
    text = data.decode("utf-8-sig", errors="replace")
    return Extracted(text, 1, "read" if text.strip() else "no text found")


def extract(name: str, data: bytes) -> Extracted:
    """Text of one document, with contact details removed."""
    suffix = Path(name).suffix.lower()
    extractor = {".pdf": extract_pdf, ".docx": extract_docx, ".xlsx": extract_xlsx}.get(suffix, extract_text)
    result = extractor(data)
    return Extracted(redact(result.text), result.pages, result.status)
