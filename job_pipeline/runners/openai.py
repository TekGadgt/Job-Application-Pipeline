"""Codex SDK provider using included ChatGPT subscription access."""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from job_pipeline.core.registry import register_runner
from job_pipeline.core.runner import RunnerError, parse_json_reply

T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = (
    "You are a data-processing engine inside a pipeline. Do not use tools or inspect "
    "files. Reply with ONLY the requested JSON object — no prose, no markdown.\n\n"
)


def _looks_non_retryable(message: str) -> bool:
    text = message.lower()
    return any(term in text for term in (
        "usage limit", "rate limit", "quota", "insufficient", "authentication",
        "unauthorized", "forbidden", "unknown model", "model not found",
    ))


@register_runner("openai")
class OpenAIRunner:
    def __init__(self, max_attempts: int = 3) -> None:
        if os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError(
                "OPENAI_API_KEY is set — refusing possible API-billed Codex usage. "
                "Unset it and authenticate with `codex login`."
            )
        self.max_attempts = max_attempts
        self._check_auth()
        self._codex_context: Any = None
        self._codex: Any = None

    @staticmethod
    def _check_auth() -> None:
        binary = shutil.which("codex")
        if not binary:
            raise RunnerError("codex CLI not found; install it and run `codex login`")
        try:
            result = subprocess.run(
                [binary, "login", "status"], capture_output=True, text=True,
                check=False, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RunnerError(f"Codex authentication check failed: {exc}") from exc
        status = f"{result.stdout}\n{result.stderr}"
        if result.returncode != 0 or "logged in using chatgpt" not in status.lower():
            raise RunnerError(
                "Codex is not authenticated with ChatGPT subscription access; "
                "run `codex login` and choose ChatGPT authentication"
            )

    def _ensure_client(self) -> Any:
        if self._codex is None:
            from openai_codex import Codex

            context = Codex()
            self._codex = context.__enter__()
            self._codex_context = context
        return self._codex

    def close(self) -> None:
        if self._codex_context is not None:
            self._codex_context.__exit__(None, None, None)
            self._codex_context = None
            self._codex = None

    def run(self, prompt: str, model: str, schema: type[T]) -> T:
        last_err: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                reply = self._query(prompt, model, schema.model_json_schema())
                return schema(**parse_json_reply(reply))
            except (RunnerError, ValidationError) as exc:
                if _looks_non_retryable(str(exc)):
                    raise RunnerError(str(exc)) from exc
                last_err = exc
            except Exception as exc:  # SDK transport/provider errors have no stable base class
                wrapped = RunnerError(f"Codex provider failed: {exc}")
                if _looks_non_retryable(str(exc)):
                    raise wrapped from exc
                last_err = wrapped
        raise RunnerError(f"no valid reply after {self.max_attempts} attempts: {last_err}")

    def _query(self, prompt: str, model: str, output_schema: dict) -> str:
        from openai_codex import ApprovalMode, Sandbox

        codex = self._ensure_client()
        thread = codex.thread_start(
            model=model,
            sandbox=Sandbox.read_only,
            approval_mode=ApprovalMode.deny_all,
            base_instructions=SYSTEM_PROMPT,
            ephemeral=True,
        )
        result = thread.run(prompt, output_schema=output_schema)
        return result.final_response
