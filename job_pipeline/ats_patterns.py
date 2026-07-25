"""ATS detection: URL patterns -> (platform, slug). Source: docs/JobBoardDetection.md."""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?P<slug>[^/?#]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/(?P<slug>[^/?#]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/(?P<slug>[^/?#]+)")),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/(?P<slug>[^/?#]+)")),
    ("workday", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", re.I)),
    ("ultipro", re.compile(r"recruiting\.ultipro\.com/(?P<slug>[^/?#]+)")),
    ("icims", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.icims\.com", re.I)),
    ("taleo", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.taleo\.net", re.I)),
    ("oraclecloud", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.oraclecloud\.com", re.I)),
    ("bamboohr", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.bamboohr\.com", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?P<slug>[^/?#]+)")),
    ("jobvite", re.compile(r"jobs\.jobvite\.com/(?P<slug>[^/?#]+)")),
    ("eightfold", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.eightfold\.ai", re.I)),
    ("teamtailor", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.teamtailor\.com", re.I)),
    ("breezy", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.breezy\.hr", re.I)),
    ("recruitee", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.recruitee\.com", re.I)),
]


def detect(url: str) -> tuple[str, str] | None:
    """Match a URL against known ATS patterns; return (platform, slug) or None."""
    for platform, pattern in PATTERNS:
        m = pattern.search(url)
        if m:
            return platform, m.group("slug")
    return None
