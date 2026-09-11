from __future__ import annotations

import subprocess

import pytest
from pydantic import BaseModel

from job_pipeline.core.runner import RunnerError
from job_pipeline.runners.openai import OpenAIRunner


class Out(BaseModel):
    name: str


def test_openai_runner_refuses_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        OpenAIRunner()


def test_openai_runner_retries_malformed_reply(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(OpenAIRunner, "_check_auth", lambda self: None)
    runner = OpenAIRunner(max_attempts=2)
    replies = iter(["bad", '{"name":"acme"}'])
    monkeypatch.setattr(runner, "_query", lambda prompt, model, schema: next(replies))
    assert runner.run("prompt", "gpt-5.6-luna", Out).name == "acme"


def test_openai_missing_cli_is_fallback_error(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("job_pipeline.runners.openai.shutil.which", lambda _: None)
    with pytest.raises(RunnerError, match="CLI not found"):
        OpenAIRunner()


@pytest.mark.parametrize("returncode,status", [(1, "Not logged in"), (0, "API key")])
def test_openai_wrong_auth_is_fallback_error(monkeypatch, returncode, status):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("job_pipeline.runners.openai.shutil.which", lambda _: "/bin/codex")
    monkeypatch.setattr("job_pipeline.runners.openai.subprocess.run", lambda *a, **k:
                        subprocess.CompletedProcess(a[0], returncode, status, ""))
    with pytest.raises(RunnerError, match="not authenticated"):
        OpenAIRunner()


def test_openai_sdk_call_uses_ephemeral_read_only_thread(monkeypatch):
    from openai_codex import ApprovalMode, Sandbox

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(OpenAIRunner, "_check_auth", lambda self: None)
    calls = {}

    class Result:
        final_response = '{"name":"acme"}'

    class Thread:
        def run(self, prompt, **kwargs):
            calls["run"] = (prompt, kwargs)
            return Result()

    class Client:
        def thread_start(self, **kwargs):
            calls["start"] = kwargs
            return Thread()

    runner = OpenAIRunner()
    monkeypatch.setattr(runner, "_ensure_client", lambda: Client())
    assert runner.run("prompt", "configured-model", Out).name == "acme"
    assert calls["start"]["model"] == "configured-model"
    assert calls["start"]["ephemeral"] is True
    assert calls["start"]["sandbox"] == Sandbox.read_only
    assert calls["start"]["approval_mode"] == ApprovalMode.deny_all
    assert calls["run"] == ("prompt", {"output_schema": Out.model_json_schema()})


@pytest.mark.integration
def test_real_openai_subscription_roundtrip():
    runner = OpenAIRunner(max_attempts=1)
    try:
        out = runner.run(
            'Return this object: {"name":"test"}', "gpt-5.6-luna", Out,
        )
        assert out.name == "test"
    finally:
        runner.close()
