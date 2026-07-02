import pytest
from pydantic import BaseModel
from job_pipeline.core.runner import RunnerError
from job_pipeline.core.sdk_runner import SDKRunner


class Out(BaseModel):
    name: str


def test_refuses_to_run_with_api_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        SDKRunner()


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = SDKRunner(max_attempts=3)
    replies = iter(["garbage", '{"name": "acme"}'])
    r._query = lambda prompt, model: next(replies)
    out = r.run("p", "haiku", Out)
    assert out.name == "acme"


def test_raises_after_max_attempts(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = SDKRunner(max_attempts=2)
    r._query = lambda prompt, model: "never json"
    with pytest.raises(RunnerError):
        r.run("p", "haiku", Out)


@pytest.mark.integration
def test_real_sdk_roundtrip(monkeypatch):
    """Opt-in: pytest -m integration. Requires logged-in Claude Code."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = SDKRunner().run(
        'Reply with ONLY this JSON object: {"name": "test"}', "haiku", Out
    )
    assert out.name == "test"
