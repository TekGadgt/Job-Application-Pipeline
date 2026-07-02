"""Deterministic orchestrator. Swappable: an AgentOrchestrator can implement
the same protocol later using StageSpec catalogs and Job.trace."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from job_pipeline.core.job import Job
from job_pipeline.core.stage import Stage


@dataclass
class RunResult:
    processed: list[Job] = field(default_factory=list)
    deferred: list[Job] = field(default_factory=list)


class Orchestrator(Protocol):
    def run(self, jobs: Sequence[Job], stages: Sequence[Stage]) -> RunResult: ...


class DeterministicOrchestrator:
    def __init__(self, max_agent_jobs: int | None = None) -> None:
        self.max_agent_jobs = max_agent_jobs

    def run(self, jobs: Sequence[Job], stages: Sequence[Stage]) -> RunResult:
        result = RunResult()
        entered_agent: set[str] = set()
        for job in jobs:
            deferred = False
            for stage in stages:
                if job.rejected or job.errored:
                    break
                if stage.spec.kind == "agent" and job.id not in entered_agent:
                    if (self.max_agent_jobs is not None
                            and len(entered_agent) >= self.max_agent_jobs):
                        deferred = True
                        break
                    entered_agent.add(job.id)
                try:
                    job = stage.run(job)
                except Exception as exc:  # noqa: BLE001 — per-job isolation
                    job.mark_errored(stage.spec.name, str(exc))
            (result.deferred if deferred else result.processed).append(job)
        return result
