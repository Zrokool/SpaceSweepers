"""Load Nimbus agent specs (prompts and schemas) from the Nimbus/agents/*.md files.

The markdown is the single source of truth: changing an agent's prompt means
editing markdown, not Python.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import ROOT

NIMBUS_DIR = ROOT / "Nimbus"


@dataclass(frozen=True)
class AgentSpec:
    name: str
    meta: dict
    system_prompt: str | None
    user_template: str | None
    output_schema: dict | None


def _block(text: str, heading: str, lang: str) -> str | None:
    """Content of the first ```lang fenced block under `## heading`."""
    m = re.search(rf"^## {re.escape(heading)}\n(?:[^\n`]*\n)*?```{lang}\n(.*?)```", text, re.S | re.M)
    return m.group(1).strip() if m else None


@lru_cache
def agent(filename: str) -> AgentSpec:
    text = (NIMBUS_DIR / "agents" / filename).read_text(encoding="utf-8")
    fm = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not fm:
        raise ValueError(f"{filename}: missing front matter")
    meta = yaml.safe_load(fm.group(1))
    schema = _block(text, "Output schema", "json")
    return AgentSpec(
        name=meta["name"],
        meta=meta,
        system_prompt=_block(text, "System prompt", "text"),
        user_template=_block(text, "User message template", "text"),
        output_schema=json.loads(schema) if schema else None,
    )


def block(filename: str, heading: str, lang: str) -> str | None:
    """Any fenced block under `## heading` in an agent spec (an agent file can hold more than one prompt)."""
    return _block((NIMBUS_DIR / "agents" / filename).read_text(encoding="utf-8"), heading, lang)


def nimbus_files() -> list[Path]:
    return sorted(NIMBUS_DIR.rglob("*.md"))


def spec_hash() -> str:
    """Identifies the exact prompts and rules a result was produced with."""
    h = hashlib.sha256()
    for p in nimbus_files():
        h.update(p.read_bytes())
    return h.hexdigest()[:16]
