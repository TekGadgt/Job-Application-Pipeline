"""AgentRunner: the swappable seam between stages and any model backend."""
from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class RunnerError(Exception):
    """Raised when a runner cannot produce a valid structured reply."""


class AgentRunner(Protocol):
    def run(self, prompt: str, model: str, schema: type[T]) -> T: ...


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

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def run(self, prompt: str, model: str, schema: type[T]) -> T:
        self.calls.append((prompt, model))
        if not self._responses:
            raise RunnerError("MockRunner exhausted")
        return schema(**self._responses.pop(0))
