"""The Job record that flows through every pipeline stage."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, UTC


@dataclass
class Job:
    # intake
    source: str
    url: str
    raw_text: str
    fetched_at: datetime
    id: str = ""                       # stable hash(url) — primary dedup key
    # after extract (agent)
    title: str = ""
    company: str = ""
    location: str = ""
    comp_text: str = ""                # verbatim comp string, for display
    comp_min: int | None = None        # numeric, parsed by the extract agent
    comp_max: int | None = None
    comp_currency: str | None = None   # e.g. "USD"
    comp_period: str | None = None     # "annual" | "hourly"
    fuzzy_key: str = ""                # normalize(company)+normalize(title)
    requirements: list[str] = field(default_factory=list)
    description: str = ""
    employer_address: str = ""         # VEC, if present in listing
    employer_phone: str = ""
    employer_email: str = ""
    # after rule stages
    location_ok: bool | None = None
    salary_ok: bool | None = None
    # after agent stages
    skill_gap: dict = field(default_factory=dict)   # {have, missing, partial}
    score: float | None = None
    score_rationale: str = ""
    # bookkeeping
    trace: list[tuple[str, str, str]] = field(default_factory=list)
    rejected: bool = False
    reject_reason: str | None = None
    reject_stage: str | None = None
    errored: bool = False
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = hashlib.sha256(self.url.encode()).hexdigest()[:16]

    def add_trace(self, stage: str, verdict: str) -> None:
        self.trace.append((stage, verdict, datetime.now(UTC).isoformat()))

    def mark_rejected(self, stage: str, reason: str) -> None:
        self.rejected = True
        self.reject_stage = stage
        self.reject_reason = reason
        self.add_trace(stage, f"rejected: {reason}")

    def mark_errored(self, stage: str, error: str) -> None:
        self.errored = True
        self.error = error
        self.add_trace(stage, f"errored: {error}")
