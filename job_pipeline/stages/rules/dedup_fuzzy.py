"""Record cross-source duplicate signal by normalized company+title+location.

Record-only since the 2026-07-23 lean re-cut: URL dedup is the only hard
dedup; a fuzzy hit traces `possible duplicate` and the job continues.
"""
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.rules.common import legacy_fuzzy_key, make_fuzzy_key
from job_pipeline.store.seen_index import SeenIndex


@register_stage("dedup_fuzzy")
class FuzzyDedupStage:
    spec = StageSpec("dedup_fuzzy", "record company+title+location key; flag possible duplicates",
                     requires=["company", "title", "location"],
                     produces=["fuzzy_key"],
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
        if self.seen.has_fuzzy(job.fuzzy_key):
            job.add_trace("dedup_fuzzy", f"possible duplicate: {job.fuzzy_key}")
        elif self.seen.has_fuzzy(legacy):
            # name the key that actually matched — legacy rows flag all locations
            job.add_trace("dedup_fuzzy", f"possible duplicate: {legacy} (legacy pre-location match)")
        else:
            job.add_trace("dedup_fuzzy", "passed")
        return job
