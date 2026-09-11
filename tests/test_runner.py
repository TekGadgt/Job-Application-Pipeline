import pytest
from pydantic import BaseModel
from job_pipeline.core.runner import (
    MockRunner, ModelChain, ModelChainEntry, parse_json_reply, RunnerError,
)


class Out(BaseModel):
    name: str


def test_mock_runner_returns_validated_schema():
    r = MockRunner([{"name": "acme"}])
    out = r.run("prompt", "haiku", Out)
    assert isinstance(out, Out) and out.name == "acme"
    assert r.calls == [("prompt", "haiku")]


def test_mock_runner_raises_when_exhausted():
    with pytest.raises(RunnerError):
        MockRunner([]).run("p", "haiku", Out)


def test_parse_json_reply_strips_code_fences():
    assert parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_reply('{"a": 1}') == {"a": 1}


def test_parse_json_reply_raises_on_garbage():
    with pytest.raises(RunnerError):
        parse_json_reply("not json")


def test_parse_json_reply_handles_nested_objects_in_fences():
    assert parse_json_reply('```json\n{"a": {"b": 1}, "c": [1, 2]}\n```') == {
        "a": {"b": 1}, "c": [1, 2],
    }


def test_model_chain_falls_through_and_short_circuits(caplog):
    failed = MockRunner([])
    success = MockRunner([{"name": "acme"}])
    never = MockRunner([{"name": "wrong"}])
    chain = ModelChain([
        ModelChainEntry("custom", failed, "luna"),
        ModelChainEntry("openai", success, "luna"),
        ModelChainEntry("anthropic", never, "haiku"),
    ])
    assert chain.run("prompt", Out).name == "acme"
    assert len(failed.calls) == 1 and len(success.calls) == 1
    assert never.calls == []
    assert "custom:luna" in caplog.text


def test_model_chain_exhaustion_lists_every_failure():
    chain = ModelChain([
        ModelChainEntry("openai", MockRunner([]), "terra"),
        ModelChainEntry("anthropic", MockRunner([]), "opus"),
    ])
    with pytest.raises(RunnerError, match="openai:terra.*anthropic:opus"):
        chain.run("prompt", Out)


def test_model_chain_does_not_hide_programming_errors():
    class BrokenRunner:
        def run(self, prompt, model, schema):
            raise TypeError("bug")

    chain = ModelChain([ModelChainEntry("broken", BrokenRunner(), "x")])
    with pytest.raises(TypeError, match="bug"):
        chain.run("prompt", Out)


def test_lazy_runner_closes_started_provider_only():
    from job_pipeline.core.runner import LazyRunner

    events = []

    class Provider:
        def __init__(self):
            events.append("started")

        def run(self, prompt, model, schema):
            return schema(name="result")

        def close(self):
            events.append("closed")

    runner = LazyRunner(Provider)
    runner.close()
    assert events == []
    runner.run("prompt", "model", Out)
    runner.close()
    assert events == ["started", "closed"]


def test_lazy_runner_does_not_swallow_billing_guard():
    from job_pipeline.core.runner import LazyRunner

    def refuse():
        raise RuntimeError("API key billing guard")

    chain = ModelChain([
        ModelChainEntry("guarded", LazyRunner(refuse), "first"),
        ModelChainEntry("fallback", MockRunner([{"name": "wrong"}]), "second"),
    ])
    with pytest.raises(RuntimeError, match="billing guard"):
        chain.run("prompt", Out)
