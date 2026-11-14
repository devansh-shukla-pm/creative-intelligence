"""Loads prompt text from the prompts/ folder (single source of truth shared with the docs and PRDs)."""
from __future__ import annotations
import re
from functools import lru_cache
from . import config

def _fenced(path, after=None):
    text = path.read_text(encoding="utf8")
    start = text.index(after) if after else 0
    a = text.index("```", start)
    a = text.index("\n", a) + 1
    b = text.index("\n```", a)
    return text[a:b]

@lru_cache(maxsize=None)
def extraction_prompt() -> str:
    return _fenced(config.PROMPTS_DIR / "extraction_prompt.md")

@lru_cache(maxsize=None)
def naming_prompt_template() -> str:
    return _fenced(config.PROMPTS_DIR / "product_naming_prompt.md", after="## Prompt")

@lru_cache(maxsize=None)
def insight_prompt() -> str:
    return (config.PROMPTS_DIR / "insight_unified_prompt.txt").read_text(encoding="utf8")
