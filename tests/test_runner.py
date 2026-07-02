import pytest
from pydantic import BaseModel
from job_pipeline.core.runner import MockRunner, parse_json_reply, RunnerError


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
