"""Drop cross-source duplicates by normalized company+title."""
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.rules.common import make_fuzzy_key
from job_pipeline.store.seen_index import SeenIndex


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
