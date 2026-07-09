"""Drop cross-source duplicates by normalized company+title+location."""
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.rules.common import legacy_fuzzy_key, make_fuzzy_key
from job_pipeline.store.seen_index import SeenIndex


@register_stage("dedup_fuzzy")
class FuzzyDedupStage:
    spec = StageSpec("dedup_fuzzy", "drop cross-source duplicates by company+title+location",
                     requires=["company", "title", "location"],
                     produces=["fuzzy_key", "rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, seen_index: SeenIndex) -> None:
        self.seen = seen_index

    def run(self, job: Job) -> Job:
        legacy = legacy_fuzzy_key(job.company, job.title)
        if legacy == "|":                     # company and title both empty: no key
            job.fuzzy_key = ""
            job.add_trace("dedup_fuzzy", "no key (empty company+title)")
            return job
        job.fuzzy_key = make_fuzzy_key(job.company, job.title, job.location)
        if self.seen.has_fuzzy(job.fuzzy_key) or self.seen.has_fuzzy(legacy):
            job.mark_rejected("dedup_fuzzy", f"duplicate role: {job.fuzzy_key}")
        else:
            job.add_trace("dedup_fuzzy", "passed")
        return job
