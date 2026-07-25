"""Extract stage: normalize a raw listing into structured fields.

The prompt is a frozen module constant for cache stability.
"""
from __future__ import annotations

from pydantic import BaseModel

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.agents.common import _fill


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


EXTRACT_PROMPT = """{source_context}{known_fields}Extract structured fields from this job listing. Reply with ONLY a JSON object:
{"title": str, "company": str, "location": str, "comp_text": str,
 "comp_min": int|null, "comp_max": int|null, "comp_currency": str|null,
 "comp_period": "annual"|"hourly"|null, "requirements": [str], "description": str,
 "employer_address": str, "employer_phone": str, "employer_email": str}
comp_min/comp_max are numbers only (e.g. "$150k" -> 150000). Use "" / null / [] when absent.
description is a 2-3 sentence summary.

LISTING:
{raw_text}"""


def _is_blank(value) -> bool:
    return value in ("", None) or value == []


@register_stage("extract")
class ExtractStage:
    spec = StageSpec("extract", "normalize a raw listing into structured fields",
                     requires=["raw_text"],
                     produces=["title", "company", "location", "comp_min", "comp_max"],
                     kind="agent", cost_tier="cheap")

    def __init__(self, runner: AgentRunner, model: str) -> None:
        self.runner, self.model = runner, model

    def run(self, job: Job) -> Job:
        blanks = [f for f in ExtractReply.model_fields if _is_blank(getattr(job, f))]
        if not blanks:
            job.add_trace("extract", "skipped: all fields prefilled")
            return job
        known = {f: getattr(job, f) for f in ExtractReply.model_fields
                 if not _is_blank(getattr(job, f))}
        known_fields = (
            f"ALREADY KNOWN (authoritative, do not contradict): {known}\n\n" if known else ""
        )
        source_context = (
            f"SOURCE CONTEXT: {job.extract_hint}\n\n" if job.extract_hint else ""
        )
        reply = self.runner.run(
            _fill(EXTRACT_PROMPT, source_context=source_context,
                  known_fields=known_fields, raw_text=job.raw_text),
            self.model, ExtractReply,
        )
        for field_name, value in reply.model_dump().items():
            if field_name in blanks:
                setattr(job, field_name, value)
        job.add_trace("extract", f"extracted ({len(blanks)} fields; {len(known)} prefilled)")
        return job
