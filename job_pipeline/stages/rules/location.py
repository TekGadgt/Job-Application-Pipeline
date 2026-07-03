"""Apply remote/metro rules to the extracted location."""
from __future__ import annotations

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec


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
