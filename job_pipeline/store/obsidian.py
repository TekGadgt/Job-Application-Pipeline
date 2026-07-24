"""Writes one Obsidian note per job; frontmatter doubles as the VEC record."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from job_pipeline.core.job import Job


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


HOURS_PER_YEAR = 2080   # annualizes hourly comp for display (salary gate deleted in Batch L)


def format_comp(job: Job) -> str:
    """Human-readable comp line for the ## Compensation section."""
    lo, hi = job.comp_min, job.comp_max
    if lo is None and hi is None:
        if job.comp_text:
            return f'Not listed — listed text: "{job.comp_text}"'
        return "Not listed"
    values = [lo, hi] if (lo is not None and hi is not None and lo != hi) \
        else [hi if hi is not None else lo]
    dollar = "$" if job.comp_currency in (None, "USD") else ""
    amounts = "–".join(f"{dollar}{v:,}" for v in values)
    label = f" {job.comp_currency}" if job.comp_currency else ""
    if job.comp_period == "hourly":
        annualized = "–".join(f"{dollar}{v * HOURS_PER_YEAR:,}" for v in values)
        text = f"{amounts}{label}/hr (≈ {annualized} annualized)"
    elif job.comp_period == "annual":
        text = f"{amounts}{label} (annual)"
    else:
        text = f"{amounts}{label}"
    if job.comp_text:
        text += f' (listed as "{job.comp_text}")'
    return text


class ObsidianWriter:
    def __init__(self, vault: Path) -> None:
        self.vault = Path(vault).expanduser()
        self.vault.mkdir(parents=True, exist_ok=True)

    def path_for(self, job: Job) -> Path:
        return self.vault / f"{_slug(job.company)}-{_slug(job.title)}-{job.id[:8]}.md"

    def is_user_touched(self, job: Job) -> bool:
        path = self.path_for(job)
        if not path.exists():
            return False
        text = path.read_text()
        try:
            _, fm, _ = text.split("---", 2)
            data = yaml.safe_load(fm) or {}
            return (data.get("status") != "to_review"
                    or data.get("application_status", "Unsubmitted") != "Unsubmitted")
        except ValueError:
            return True   # malformed note: treat as user-owned, never clobber

    def write(self, job: Job) -> Path:
        possible_dup = any(
            stage == "dedup_fuzzy" and verdict.startswith("possible duplicate")
            for stage, verdict, _ in job.trace
        )
        frontmatter = {
            "company": job.company,
            "position": job.title,
            "location": job.location,
            "employer_address": job.employer_address,
            "employer_phone": job.employer_phone,
            "employer_email": job.employer_email,
            "employer_contact_person": "",
            "date_found": job.fetched_at.date().isoformat(),
            "date_of_contact": "",
            "source_url": job.url,
            "type_of_work": job.title,
            "result_of_contact": "found",
            "application_status": "Unsubmitted",
            "score": job.score,
            "comp_min": job.comp_min,
            "comp_max": job.comp_max,
            "comp_currency": job.comp_currency,
            "comp_period": job.comp_period,
            "status": "to_review",
            "job_id": job.id,
            "role_key": job.fuzzy_key or None,
            "possible_duplicate": possible_dup,
        }
        gap = job.skill_gap or {}
        body = (
            f"## Fit — {job.score}/100\n{job.score_rationale}\n\n"
            f"## Compensation\n{format_comp(job)}\n\n"
            f"## Skill gap\n"
            f"- Have: {', '.join(gap.get('have', []))}\n"
            f"- Missing: {', '.join(gap.get('missing', []))}\n"
            f"- Partial: {', '.join(gap.get('partial', []))}\n\n"
            f"## Description\n{job.description}\n"
        )
        path = self.path_for(job)
        path.write_text(
            "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body
        )
        return path
