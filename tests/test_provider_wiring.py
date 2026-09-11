from __future__ import annotations

from datetime import UTC, datetime

import pytest

from job_pipeline.config import Limits, OutputConfig, PipelineConfig, Profile
from job_pipeline.core.job import Job
from job_pipeline.core.pipeline import build_stages, run_pipeline
from job_pipeline.core.registry import register_runner
from job_pipeline.core.runner import RunnerError
from job_pipeline.store.obsidian import ObsidianWriter
from job_pipeline.store.seen_index import SeenIndex


def test_build_stages_reuses_one_instance_per_provider(tmp_path):
    made = []

    @register_runner("wiring-shared")
    class SharedRunner:
        def __init__(self, marker=None):
            self.marker = marker
            made.append(self)

        def run(self, prompt, model, schema):
            return schema()

    cfg = PipelineConfig(
        stages=["extract", "skill_gap", "score"],
        models={
            "extract": ["wiring-shared:luna"],
            "skill_gap": ["wiring-shared:luna"],
            "score": ["wiring-shared:terra"],
        },
        runners={"wiring-shared": {"marker": "configured"}},
        output=OutputConfig(vault=tmp_path / "vault"),
    )
    instances = {}
    stages = build_stages(
        cfg, Profile(), SeenIndex(tmp_path / "seen.sqlite"), None,
        ObsidianWriter(tmp_path / "vault"), provider_instances=instances,
    )
    assert made == []  # no provider starts until its first call
    from pydantic import BaseModel
    class BaseModelReply(BaseModel):
        pass
    for stage in stages:
        stage.chain.run("prompt", BaseModelReply)
    assert len(made) == 1 and made[0].marker == "configured"
    assert all(stage.chain.entries[0].runner.instance is made[0] for stage in stages)


def test_unknown_provider_fails_while_building_stages(tmp_path):
    cfg = PipelineConfig(
        stages=["extract"], models={"extract": ["not-installed:model"]},
        output=OutputConfig(vault=tmp_path / "vault"),
    )
    with pytest.raises(KeyError, match="not-installed"):
        build_stages(
            cfg, Profile(), SeenIndex(tmp_path / "seen.sqlite"), None,
            ObsidianWriter(tmp_path / "vault"),
        )


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_pipeline_publishes_through_second_provider_after_fallback(tmp_path, cleanup_fails):
    replies = [
        {
            "title": "Engineer", "company": "Acme", "location": "Remote",
            "comp_text": "$150k", "comp_min": 150000, "comp_max": 150000,
            "comp_currency": "USD", "comp_period": "annual",
            "requirements": ["python"], "description": "Build.",
        },
        {"have": ["python"], "missing": [], "partial": []},
        {"score": 90, "rationale": "Strong fit"},
    ]

    @register_runner("e2e-failing")
    class FailingRunner:
        def run(self, prompt, model, schema):
            raise RunnerError("subscription limit reached")

    @register_runner("e2e-success")
    class SuccessRunner:
        def run(self, prompt, model, schema):
            return schema(**replies.pop(0))

        def close(self):
            if cleanup_fails:
                raise RuntimeError("cleanup failed")

    cfg = PipelineConfig(
        stages=["dedup", "extract", "skill_gap", "score", "publish"],
        models={
            name: ["e2e-failing:first", "e2e-success:second"]
            for name in ("extract", "skill_gap", "score")
        },
        output=OutputConfig(vault=tmp_path / "vault"),
        limits=Limits(max_agent_jobs_per_run=10),
    )
    job = Job(
        source="test", url="https://example.com/job", raw_text="Python role",
        fetched_at=datetime.now(UTC),
    )

    class Source:
        def fetch(self):
            return [job]
        def on_terminal(self, job):
            pass

    summary = run_pipeline(
        cfg, Profile(body="Python developer"), sources=[Source()],
        db_path=tmp_path / "seen-e2e.sqlite",
    )
    assert summary.published == 1
    assert replies == []
    assert summary.notes[0].exists()
    seen = SeenIndex(tmp_path / "seen-e2e.sqlite")
    try:
        assert seen.has_url(job.id)
    finally:
        seen.close()


def test_startup_failure_falls_back_and_is_cached(tmp_path):
    from pydantic import BaseModel

    class Reply(BaseModel):
        name: str

    attempts = []

    @register_runner("startup-unavailable")
    class Unavailable:
        def __init__(self):
            attempts.append(1)
            raise RunnerError("not authenticated")

    cfg = PipelineConfig(
        stages=["extract"],
        models={"extract": ["startup-unavailable:first", "mock:second"]},
        runners={"mock": {"responses": [{"name": "one"}, {"name": "two"}]}},
        output=OutputConfig(vault=tmp_path),
    )
    stages = build_stages(cfg, Profile(), SeenIndex(tmp_path / "seen.sqlite"),
                          None, ObsidianWriter(tmp_path))
    assert attempts == []
    assert stages[0].chain.run("prompt", Reply).name == "one"
    assert stages[0].chain.run("prompt", Reply).name == "two"
    assert attempts == [1]


def test_unused_fallback_is_never_started(tmp_path):
    from pydantic import BaseModel

    class Reply(BaseModel):
        name: str

    @register_runner("must-not-start")
    class Unused:
        def __init__(self):
            raise AssertionError("unused fallback started")

    cfg = PipelineConfig(
        stages=["extract"], models={"extract": ["mock:first", "must-not-start:second"]},
        runners={"mock": {"responses": [{"name": "first"}]}},
        output=OutputConfig(vault=tmp_path),
    )
    stages = build_stages(cfg, Profile(), SeenIndex(tmp_path / "seen.sqlite"),
                          None, ObsidianWriter(tmp_path))
    assert stages[0].chain.run("prompt", Reply).name == "first"
