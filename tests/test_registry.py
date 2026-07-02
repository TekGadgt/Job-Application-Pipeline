import pytest
from job_pipeline.core.registry import (
    register_stage, get_stage, register_source, get_source,
    register_seeder, get_seeder,
)
from job_pipeline.core.stage import StageSpec


def test_register_and_get_stage():
    @register_stage("demo")
    class Demo:
        spec = StageSpec(name="demo", purpose="test", requires=[], produces=[],
                         kind="deterministic", cost_tier="free")
        def run(self, job):
            return job
    assert get_stage("demo") is Demo


def test_unknown_name_raises_keyerror_listing_known():
    with pytest.raises(KeyError, match="demo"):
        get_stage("nope")


def test_source_and_seeder_registries_are_separate():
    @register_source("src")
    class Src: ...
    @register_seeder("seed")
    class Seed: ...
    assert get_source("src") is Src and get_seeder("seed") is Seed
    with pytest.raises(KeyError):
        get_source("seed")
