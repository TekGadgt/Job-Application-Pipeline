"""Skill-gap stage: compare resume/skills to job requirements.

The prompt is a frozen module constant for cache stability.
"""
from __future__ import annotations

from pydantic import BaseModel

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.agents.common import _fill


class SkillGapReply(BaseModel):
    have: list[str] = []
    missing: list[str] = []
    partial: list[str] = []


SKILL_GAP_PROMPT = """Compare this candidate against the job requirements. Reply with ONLY a JSON object:
{"have": [str], "missing": [str], "partial": [str]}

CANDIDATE PROFILE:
{profile_body}

JOB REQUIREMENTS:
{requirements}

JOB DESCRIPTION:
{description}"""


@register_stage("skill_gap")
class SkillGapStage:
    spec = StageSpec("skill_gap", "compare resume/skills to job requirements",
                     requires=["requirements", "description"], produces=["skill_gap"],
                     kind="agent", cost_tier="mid")

    def __init__(self, runner: AgentRunner, model: str, profile: Profile) -> None:
        self.runner, self.model, self.profile = runner, model, profile

    def run(self, job: Job) -> Job:
        reply = self.runner.run(
            _fill(
                SKILL_GAP_PROMPT,
                profile_body=self.profile.body,
                requirements=job.requirements,
                description=job.description,
            ),
            self.model, SkillGapReply,
        )
        job.skill_gap = reply.model_dump()
        job.add_trace("skill_gap", "analyzed")
        return job
