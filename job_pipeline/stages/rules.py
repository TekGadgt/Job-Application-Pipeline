"""The free deterministic filter stages. No model tokens are spent here."""
from __future__ import annotations

import re

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.store.seen_index import SeenIndex

HOURS_PER_YEAR = 2080


def make_fuzzy_key(company: str, title: str) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return f"{norm(company)}|{norm(title)}"


@register_stage("dedup")
class DedupStage:
    spec = StageSpec("dedup", "drop jobs whose URL was already seen",
                     requires=["id"], produces=["rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, seen_index: SeenIndex) -> None:
        self.seen = seen_index

    def run(self, job: Job) -> Job:
        if self.seen.has_url(job.id):
            job.mark_rejected("dedup", "url already seen")
        else:
            job.add_trace("dedup", "passed")
        return job


@register_stage("hard_filter")
class HardFilterStage:
    spec = StageSpec("hard_filter", "reject listings matching the blocklist keywords",
                     requires=["raw_text"], produces=["rejected", "reject_reason"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, profile: Profile) -> None:
        self.patterns = [
            (kw, re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE))
            for kw in profile.blocklist
        ]

    def run(self, job: Job) -> Job:
        for kw, pat in self.patterns:
            if pat.search(job.raw_text):
                job.mark_rejected("hard_filter", f"blocklist: {kw}")
                return job
        job.add_trace("hard_filter", "passed")
        return job


@register_stage("dedup_fuzzy")
class FuzzyDedupStage:
    spec = StageSpec("dedup_fuzzy", "drop cross-source duplicates by company+title",
                     requires=["company", "title"], produces=["fuzzy_key", "rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, seen_index: SeenIndex) -> None:
        self.seen = seen_index

    def run(self, job: Job) -> Job:
        job.fuzzy_key = make_fuzzy_key(job.company, job.title)
        if self.seen.has_fuzzy(job.fuzzy_key):
            job.mark_rejected("dedup_fuzzy", f"duplicate role: {job.fuzzy_key}")
        else:
            job.add_trace("dedup_fuzzy", "passed")
        return job


@register_stage("location")
class LocationStage:
    spec = StageSpec("location", "apply remote/metro rules to the extracted location",
                     requires=["location"], produces=["location_ok", "rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, profile: Profile) -> None:
        self.rules = profile.locations

    def run(self, job: Job) -> Job:
        loc = job.location.lower()
        ok = (self.rules.remote and "remote" in loc) or any(
            metro.lower() in loc for metro in self.rules.allowed_metros
        )
        job.location_ok = ok
        if ok:
            job.add_trace("location", "passed")
        else:
            job.mark_rejected("location", f"location not allowed: {job.location!r}")
        return job


@register_stage("salary")
class SalaryStage:
    spec = StageSpec("salary", "compare extracted comp against the salary floor",
                     requires=["comp_max", "comp_period"], produces=["salary_ok", "rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, profile: Profile) -> None:
        self.floor = profile.salary_floor
        self.not_listed = profile.salary_not_listed

    def run(self, job: Job) -> Job:
        if self.floor is None:
            job.salary_ok = True
            job.add_trace("salary", "no floor configured")
            return job
        if job.comp_max is None:
            if self.not_listed == "reject":
                job.salary_ok = False
                job.mark_rejected("salary", "salary not listed")
            else:
                job.salary_ok = True
                job.add_trace("salary", "not listed; kept per profile")
            return job
        annual = job.comp_max * (HOURS_PER_YEAR if job.comp_period == "hourly" else 1)
        job.salary_ok = annual >= self.floor
        if job.salary_ok:
            job.add_trace("salary", f"passed ({annual} >= {self.floor})")
        else:
            job.mark_rejected("salary", f"below floor ({annual} < {self.floor})")
        return job
