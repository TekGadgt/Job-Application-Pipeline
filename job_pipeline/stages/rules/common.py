"""Helpers shared by more than one rule stage."""
from __future__ import annotations

import re

HOURS_PER_YEAR = 2080


def make_fuzzy_key(company: str, title: str) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return f"{norm(company)}|{norm(title)}"
