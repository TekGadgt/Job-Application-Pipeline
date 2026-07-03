"""Compare extracted comp against the profile's salary floor."""
from __future__ import annotations

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.rules.common import HOURS_PER_YEAR


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
