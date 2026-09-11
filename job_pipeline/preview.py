"""Offline CLI preview: synthetic listings and replies, temporary output only."""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from job_pipeline.config import OutputConfig, PipelineConfig, Profile
from job_pipeline.core.job import Job
from job_pipeline.core.pipeline import RunSummary, run_pipeline
from job_pipeline.core.runner import RunnerError
from job_pipeline.stages.agents.extract import ExtractReply
from job_pipeline.stages.agents.score import ScoreReply
from job_pipeline.stages.agents.skill_gap import SkillGapReply


class PreviewRunner:
    def run(self, prompt, model, schema):
        replies = {
            ExtractReply: {"title": "Preview Engineer", "company": "Example Company",
                           "description": "Synthetic listing for an offline preview."},
            SkillGapReply: {"have": [], "missing": [], "partial": []},
            ScoreReply: {"score": 50, "rationale": "Synthetic preview score; not a fit assessment."},
        }
        if schema not in replies:
            raise RunnerError(f"No preview fixture for {schema.__name__}")
        return schema(**replies[schema])


class PreviewSource:
    def __init__(self, urls: list[str]) -> None:
        self.urls = urls or ["https://example.invalid/preview-job"]

    def fetch(self):
        return [Job(source="preview", url=url, fetched_at=datetime.now(UTC),
                    raw_text="Synthetic listing for an offline preview.") for url in self.urls]

    def on_terminal(self, job):
        pass


def run_preview(cfg: PipelineConfig, profile: Profile, urls: list[str]) -> RunSummary:
    with TemporaryDirectory(prefix="job-pipeline-preview-") as temp:
        preview_cfg = cfg.model_copy(update={
            "sources": [], "seeders": [], "output": OutputConfig(vault=Path(temp)),
        })
        summary = run_pipeline(preview_cfg, profile, runner_override=PreviewRunner(),
                               sources=[PreviewSource(urls)])
        # Temporary notes are intentionally discarded; never print nonexistent paths.
        summary.notes = []
        return summary
