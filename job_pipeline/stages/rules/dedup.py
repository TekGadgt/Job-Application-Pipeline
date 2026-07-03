"""Drop jobs whose URL was already seen."""
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.store.seen_index import SeenIndex


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
