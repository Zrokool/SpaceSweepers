"""The PSI Source page tells a story in numbers. They come from the snapshot, and the story's arithmetic must add up."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIEW = (ROOT / "static" / "js" / "views" / "sources.js").read_text(encoding="utf-8")


def test_the_page_is_named_psi_source_and_keeps_its_address():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    assert '<a href="#/sources" data-view="sources">PSI Source</a>' in html and ">References<" not in html
    assert 'text: "PSI Source"' in VIEW                                                        # the page's own eyebrow


def test_the_story_is_in_five_steps_with_the_detail_kept_in_an_audit():
    for heading in ("The source", "What PSI holds for each investigation", "What we could chart", "How the numbers are kept honest", "Cite and check"):
        assert heading in VIEW
    assert 'class: "card audit"' in VIEW and "Table-by-table audit" in VIEW
    assert "Claude Code (Anthropic)" in VIEW and "SI never produces a number" in VIEW          # the SI acknowledgement and rule are kept


def test_no_count_is_typed_into_the_page_so_it_cannot_go_out_of_date():
    assert not re.search(r"1,411|\b367\b|2,353|\b1,593\b|\b8,077\b|\b26 investigations\b", VIEW)


def test_the_funnel_adds_up(client):
    meta = client.get("/api/meta").json()
    tbl, counts = meta["tables"], meta["counts"]
    unusable = tbl["by_status"].get("not mappable", 0) + tbl["by_status"].get("superseded", 0)
    assert tbl["by_status"].get("parsed", 0) + unusable == tbl["total"]                        # every downloaded table is placed in one step
    assert sum(tbl["by_reason"].values()) == unusable                                          # and every unusable one has a stated reason
    with_tables = [i for i in client.get("/api/investigations").json()["investigations"] if i["table_rows"] > 0]
    assert counts["investigations_with_tests"] <= len(with_tables) <= counts["investigations"]
