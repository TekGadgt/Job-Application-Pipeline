"""Reject listings matching the profile's blocklist keywords."""
from __future__ import annotations

import re

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec


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
