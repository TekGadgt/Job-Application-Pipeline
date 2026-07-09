"""Reject jobs scoring below the profile's floor. Runs after score, before publish."""
from __future__ import annotations

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec


@register_stage("score_floor")
class ScoreFloorStage:
    spec = StageSpec("score_floor", "reject jobs scoring below the profile's floor",
                     requires=["score"], produces=["rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, profile: Profile) -> None:
        self.floor = profile.score_floor

    def run(self, job: Job) -> Job:
        if self.floor is None:
            job.add_trace("score_floor", "no floor configured")
            return job
        if job.score is None:
            job.add_trace("score_floor", "no score present; passed")
            return job
        if job.score >= self.floor:
            job.add_trace("score_floor", f"passed ({job.score} >= {self.floor})")
        else:
            job.mark_rejected("score_floor", f"score {job.score} below floor {self.floor}")
        return job
