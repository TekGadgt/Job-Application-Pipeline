from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.store.obsidian import ObsidianWriter


@register_stage("publish")
class PublishStage:
    spec = StageSpec("publish", "write the Obsidian note (VEC-ready frontmatter)",
                     requires=["title", "company", "score"], produces=[],
                     kind="deterministic", cost_tier="free")

    def __init__(self, writer: ObsidianWriter, force: bool = False) -> None:
        self.writer, self.force = writer, force

    def run(self, job: Job) -> Job:
        if not self.force and self.writer.is_user_touched(job):
            job.add_trace("publish", "skipped: note edited by user")
            return job
        path = self.writer.write(job)
        job.add_trace("publish", f"wrote {path.name}")
        return job
