"""Load the packaged data once and fail loudly if it is unusable: `python -m app.warm`.

Run at image build time (so a broken or stale snapshot never ships) and at start-up (so the first visitor does not pay for the
catalog and the search library). Everything is rebuilt in memory from `data/`, so this is the whole "cache".
"""

from __future__ import annotations

import logging
import sys

from app.catalog import get_catalog
from app.config import get_settings
from app.insights.library import get_library

log = logging.getLogger("spacesweepers")


def warm() -> dict:
    data_dir = get_settings().data_dir
    catalog = get_catalog(data_dir)
    library = get_library(data_dir)
    stale = [i["id"] for i in catalog.investigations.values() if str(i.get("tables_status", "")).startswith("stale")]
    summary = {"investigations": len(catalog.investigations), "tests": len(catalog.tests), "library_items": len(library.items), "stale": stale}
    if summary["investigations"] != 26 or not summary["tests"] or not summary["library_items"]:
        raise RuntimeError(f"packaged data is incomplete: {summary}")
    if stale:
        raise RuntimeError(f"data refresh needed, tables changed after they were mapped: {stale}")
    return summary


if __name__ == "__main__":
    try:
        print(warm())
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
