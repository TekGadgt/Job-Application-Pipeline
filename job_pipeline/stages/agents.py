"""The three agent stages. Prompts are frozen module constants for cache stability."""
from __future__ import annotations

from pydantic import BaseModel, Field

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.core.stage import StageSpec


def _fill(template: str, **values: object) -> str:
    """Brace-safe template fill: values may contain literal { } freely."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out


class ExtractReply(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    comp_text: str = ""
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str | None = None
    comp_period: str | None = None       # "annual" | "hourly"
    requirements: list[str] = []
    description: str = ""
    employer_address: str = ""
    employer_phone: str = ""
    employer_email: str = ""


class SkillGapReply(BaseModel):
    have: list[str] = []
    missing: list[str] = []
    partial: list[str] = []


class ScoreReply(BaseModel):
    score: float = Field(ge=0, le=100)
    rationale: str


EXTRACT_PROMPT = """Extract structured fields from this job listing. Reply with ONLY a JSON object:
{"title": str, "company": str, "location": str, "comp_text": str,
 "comp_min": int|null, "comp_max": int|null, "comp_currency": str|null,
 "comp_period": "annual"|"hourly"|null, "requirements": [str], "description": str,
 "employer_address": str, "employer_phone": str, "employer_email": str}
comp_min/comp_max are numbers only (e.g. "$150k" -> 150000). Use "" / null / [] when absent.
description is a 2-3 sentence summary.

LISTING:
{raw_text}"""

SKILL_GAP_PROMPT = """Compare this candidate against the job requirements. Reply with ONLY a JSON object:
{"have": [str], "missing": [str], "partial": [str]}

CANDIDATE PROFILE:
{profile_body}

JOB REQUIREMENTS:
{requirements}

JOB DESCRIPTION:
{description}"""

SCORE_PROMPT = """Score this job 0-100 for fit against the candidate's profile and preferences.
Reply with ONLY a JSON object: {"score": number, "rationale": str}
The rationale should be 2-4 sentences naming the decisive factors.

CANDIDATE PROFILE AND PREFERENCES:
{profile_body}

JOB: {title} at {company} ({location}) — {comp_text}
DESCRIPTION: {description}
SKILL GAP: {skill_gap}"""


@register_stage("extract")
class ExtractStage:
    spec = StageSpec("extract", "normalize a raw listing into structured fields",
                     requires=["raw_text"],
                     produces=["title", "company", "location", "comp_min", "comp_max"],
                     kind="agent", cost_tier="cheap")

    def __init__(self, runner: AgentRunner, model: str) -> None:
        self.runner, self.model = runner, model

    def run(self, job: Job) -> Job:
        reply = self.runner.run(
            _fill(EXTRACT_PROMPT, raw_text=job.raw_text), self.model, ExtractReply
        )
        for field_name, value in reply.model_dump().items():
            setattr(job, field_name, value)
        job.add_trace("extract", "extracted")
        return job


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
