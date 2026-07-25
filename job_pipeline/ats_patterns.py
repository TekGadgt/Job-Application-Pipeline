"""ATS detection: URL patterns -> (platform, slug). Source: docs/JobBoardDetection.md."""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?<![\w-])(?:boards|job-boards)\.greenhouse\.io/(?P<slug>[^/?#]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/(?P<slug>[^/?#]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/(?P<slug>[^/?#]+)")),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/(?P<slug>[^/?#]+)")),
    ("workday", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", re.I)),
    ("ultipro", re.compile(r"recruiting\.ultipro\.com/(?P<slug>[^/?#]+)")),
    ("icims", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.icims\.com", re.I)),
    ("taleo", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.taleo\.net", re.I)),
    ("oraclecloud", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.oraclecloud\.com/(?:.*/)?(?:hcmUI/CandidateExperience|hcmRestApi)", re.I)),
    ("bamboohr", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.bamboohr\.com/careers", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?P<slug>[^/?#]+)")),
    ("jobvite", re.compile(r"jobs\.jobvite\.com/(?P<slug>[^/?#]+)")),
    # Path-qualified like oraclecloud/bamboohr above: {company}.eightfold.ai/careers.
    # Note: the multi-tenant form app.eightfold.ai/careers?domain=... is not
    # distinguishable per-company from the URL alone and is still not handled.
    ("eightfold", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.eightfold\.ai/careers", re.I)),
    ("teamtailor", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.teamtailor\.com", re.I)),
    ("breezy", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.breezy\.hr", re.I)),
    ("recruitee", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.recruitee\.com", re.I)),
]


GREENHOUSE_RESERVED_SLUGS = {"embed", "job_app", "job_board"}


def _greenhouse_company_slug(url: str, slug: str) -> str | None:
    """Resolve the real company slug for a greenhouse URL.

    Embed wrapper URLs (e.g. /embed/job_app?...&for=acme) put a reserved
    path segment where the company would normally be, with the actual
    company carried in the `for=` query param instead. Prefer that; if
    there's no usable company token, signal failure (None) rather than
    registering the reserved segment as a bogus company.
    """
    if slug.lower() not in GREENHOUSE_RESERVED_SLUGS:
        return slug
    m = re.search(r"[?&]for=([^&#]+)", url)
    return m.group(1) if m else None


def detect(url: str) -> tuple[str, str] | None:
    """Match a URL against known ATS patterns; return (platform, slug) or None."""
    for platform, pattern in PATTERNS:
        m = pattern.search(url)
        if not m:
            continue
        slug = m.group("slug")
        if platform == "greenhouse":
            slug = _greenhouse_company_slug(url, slug)
            if slug is None:
                return None
        if slug.lower() != "www":
            return platform, slug
    return None
