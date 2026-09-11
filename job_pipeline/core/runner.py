"""AgentRunner: the swappable seam between stages and any model backend."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)
log = logging.getLogger("job_pipeline")


class RunnerError(Exception):
    """Raised when a runner cannot produce a valid structured reply."""


class AgentRunner(Protocol):
    def run(self, prompt: str, model: str, schema: type[T]) -> T: ...


class LazyRunner:
    """Initialize a provider on first use and remember unavailable providers per run."""

    def __init__(self, factory: Callable[[], AgentRunner]) -> None:
        self.factory = factory
        self.instance: AgentRunner | None = None
        self.startup_error: RunnerError | None = None

    def run(self, prompt: str, model: str, schema: type[T]) -> T:
        if self.startup_error is not None:
            raise self.startup_error
        if self.instance is None:
            try:
                self.instance = self.factory()
            except RunnerError as exc:
                self.startup_error = exc
                raise
        return self.instance.run(prompt, model, schema)

    def close(self) -> None:
        if self.instance is not None:
            close = getattr(self.instance, "close", None)
            if close is not None:
                close()


@dataclass(frozen=True)
class ModelChainEntry:
    provider: str
    runner: AgentRunner
    model: str


class ModelChain:
    """Try provider/model entries in order until one returns a valid result."""

    def __init__(self, entries: list[ModelChainEntry]) -> None:
        if not entries:
            raise ValueError("model chain must not be empty")
        self.entries = entries

    def run(self, prompt: str, schema: type[T]) -> T:
        failures: list[str] = []
        for entry in self.entries:
            label = f"{entry.provider}:{entry.model}"
            try:
                return entry.runner.run(prompt, entry.model, schema)
            except RunnerError as exc:
                failures.append(f"{label}: {exc}")
                log.warning("model %s failed; trying fallback: %s", label, exc)
        raise RunnerError("all model-chain entries failed: " + "; ".join(failures))


def parse_json_reply(text: str) -> dict:
    """Extract a JSON object from a model reply, tolerating ```json fences."""
    stripped = text.strip()
    stripped = re.sub(r"^```(?:json)?\s*\n?|\n?```\s*$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as e:
        raise RunnerError(f"model reply was not valid JSON: {e}") from e


class MockRunner:
    """Test double: returns queued dicts, validated through the requested schema."""

    def __init__(self, responses: list[dict] | None = None) -> None:
        self._responses = list(responses or [])
        self.calls: list[tuple[str, str]] = []

    def run(self, prompt: str, model: str, schema: type[T]) -> T:
        self.calls.append((prompt, model))
        if not self._responses:
            raise RunnerError("MockRunner exhausted")
        return schema(**self._responses.pop(0))
