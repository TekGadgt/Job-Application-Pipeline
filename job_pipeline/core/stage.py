"""Stage protocol and the self-describing StageSpec descriptor."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from job_pipeline.core.job import Job


@dataclass(frozen=True)
class StageSpec:
    name: str
    purpose: str                    # human/LLM-readable
    requires: list[str]             # Job fields this stage reads
    produces: list[str]             # Job fields this stage sets
    kind: Literal["deterministic", "agent"]
    cost_tier: Literal["free", "cheap", "mid", "expensive"]


@runtime_checkable
class Stage(Protocol):
    spec: StageSpec

    def run(self, job: Job) -> Job: ...
