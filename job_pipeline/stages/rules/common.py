"""Helpers shared by more than one rule stage."""
from __future__ import annotations

import re

HOURS_PER_YEAR = 2080


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def make_fuzzy_key(company: str, title: str, location: str = "") -> str:
    """Location-aware dedup key. The same role listed for different
    locations is a different job; see the 2026-07-09 dedup spec."""
    return f"{_norm(company)}|{_norm(title)}|{_norm(location)}"


def legacy_fuzzy_key(company: str, title: str) -> str:
    """Pre-location key format. Seen-index rows written before 2026-07
    hold this form and block the role in ALL locations."""
    return f"{_norm(company)}|{_norm(title)}"
