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
        agent_slots_used = 0
        for job in jobs:
            deferred = False
            for stage in stages:
                if job.rejected or job.errored:
                    break
                if stage.spec.kind == "agent" and not self._entered_agent(job):
                    if (self.max_agent_jobs is not None
                            and agent_slots_used >= self.max_agent_jobs):
                        deferred = True
                        break
                    agent_slots_used += 1
                    job._entered_agent = True   # per-run marker, not persisted
                try:
                    job = stage.run(job)
                except Exception as exc:  # noqa: BLE001 — per-job isolation
                    job.mark_errored(stage.spec.name, str(exc))
            (result.deferred if deferred else result.processed).append(job)
        return result

    @staticmethod
    def _entered_agent(job: Job) -> bool:
        return getattr(job, "_entered_agent", False)
