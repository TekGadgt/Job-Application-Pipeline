"""Score stage: final fit judgment with rationale.

The prompt is a frozen module constant for cache stability.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.agents.common import _fill


class ScoreReply(BaseModel):
    score: float = Field(ge=0, le=100)
    rationale: str


SCORE_PROMPT = """Score this job 0-100 for fit against the candidate's profile and preferences.
Reply with ONLY a JSON object: {"score": number, "rationale": str}
The rationale should be 2-4 sentences naming the decisive factors.

CANDIDATE PROFILE AND PREFERENCES:
{profile_body}

JOB: {title} at {company} ({location}) — {comp_text}
DESCRIPTION: {description}
SKILL GAP: {skill_gap}"""


@register_stage("score")
class ScoreStage:
    spec = StageSpec("score", "final fit judgment with rationale",
                     requires=["title", "company", "description", "skill_gap"],
                     produces=["score", "score_rationale"],
                     kind="agent", cost_tier="expensive")

    def __init__(self, runner: AgentRunner, model: str, profile: Profile) -> None:
        self.runner, self.model, self.profile = runner, model, profile

    def run(self, job: Job) -> Job:
        reply = self.runner.run(
            _fill(
                SCORE_PROMPT,
                profile_body=self.profile.body,
                title=job.title, company=job.company, location=job.location,
                comp_text=job.comp_text, description=job.description,
                skill_gap=job.skill_gap,
            ),
            self.model, ScoreReply,
        )
        job.score, job.score_rationale = reply.score, reply.rationale
        job.add_trace("score", f"scored {reply.score}")
        return job
