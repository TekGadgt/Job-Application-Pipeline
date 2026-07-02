"""AgentRunner backed by the Claude Agent SDK (rides Claude Code subscription auth).

Billing guard: a set ANTHROPIC_API_KEY silently flips the SDK to pay-as-you-go
API credits. This project is subscription-only, so we refuse to start.
"""
from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from job_pipeline.core.runner import RunnerError, parse_json_reply

T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = (
    "You are a data-processing engine inside a pipeline. "
    "Reply with ONLY the requested JSON object — no prose, no markdown."
)


class SDKRunner:
    def __init__(self, max_attempts: int = 3) -> None:
        if os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is set — this would bill API credits instead of "
                "your subscription. Unset it (subscription auth comes from your "
                "logged-in Claude Code session)."
            )
        self.max_attempts = max_attempts

    def run(self, prompt: str, model: str, schema: type[T]) -> T:
        last_err: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                reply = self._query(prompt, model)
                return schema(**parse_json_reply(reply))
            except (RunnerError, ValidationError) as e:
                last_err = e
        raise RunnerError(f"no valid reply after {self.max_attempts} attempts: {last_err}")

    def _query(self, prompt: str, model: str) -> str:
        """All SDK/async plumbing lives here — the seam mocked in unit tests."""
        import anyio
        from claude_agent_sdk import (
            AssistantMessage, ClaudeAgentOptions, TextBlock, query,
        )

        async def go() -> str:
            options = ClaudeAgentOptions(
                model=model,
                system_prompt=SYSTEM_PROMPT,
                max_turns=1,
                allowed_tools=[],
            )
            text = ""
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text += block.text
            return text

        return anyio.run(go)
