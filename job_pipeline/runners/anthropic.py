"""Claude Agent SDK provider using Claude Code subscription authentication."""
from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from job_pipeline.core.registry import register_runner
from job_pipeline.core.runner import RunnerError, parse_json_reply

T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = (
    "You are a data-processing engine inside a pipeline. "
    "Reply with ONLY the requested JSON object — no prose, no markdown."
)


@register_runner("claude")
@register_runner("anthropic")
class AnthropicRunner:
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
            except (RunnerError, ValidationError) as exc:
                last_err = exc
            except Exception as exc:  # SDK transport/provider errors have no stable base class
                last_err = RunnerError(f"Anthropic provider failed: {exc}")
        raise RunnerError(f"no valid reply after {self.max_attempts} attempts: {last_err}")

    def _query(self, prompt: str, model: str) -> str:
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


# Compatibility for older imports while the canonical provider name is anthropic.
SDKRunner = AnthropicRunner
