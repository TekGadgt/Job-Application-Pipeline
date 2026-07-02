"""Writes one Obsidian note per job; frontmatter doubles as the VEC record."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from job_pipeline.core.job import Job


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


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
            return (yaml.safe_load(fm) or {}).get("status") != "to_review"
        except ValueError:
            return True   # malformed note: treat as user-owned, never clobber

    def write(self, job: Job) -> Path:
        frontmatter = {
            "company": job.company,
            "position": job.title,
            "employer_address": job.employer_address,
            "employer_phone": job.employer_phone,
            "employer_email": job.employer_email,
            "employer_contact_person": "",
            "date_found": job.fetched_at.date().isoformat(),
            "date_of_contact": "",
            "source_url": job.url,
            "type_of_work": job.title,
            "result_of_contact": "found",
            "score": job.score,
            "status": "to_review",
            "job_id": job.id,
        }
        gap = job.skill_gap or {}
        body = (
            f"## Fit — {job.score}/100\n{job.score_rationale}\n\n"
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
