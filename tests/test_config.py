import pytest
from pydantic import ValidationError
from job_pipeline.config import load_profile, load_pipeline_config

PROFILE = """---
salary_floor: 140000
locations: {remote: true, allowed_metros: ["Richmond, VA"]}
blocklist: [crypto, web3]
must_have_skills: [python]
nice_to_have: [rust]
salary_not_listed: keep
---
## Base resume
I write Python.
"""

PIPELINE = """
sources:
  - {type: rss, url: "https://example.com/feed"}
seeders: []
stages: [dedup, hard_filter]
models: {extract: haiku, skill_gap: sonnet, score: opus}
output: {vault: /tmp/vault, keep_rejects: true}
limits: {max_agent_jobs_per_run: 40}
"""


def test_load_profile_parses_frontmatter_and_body(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text(PROFILE)
    prof = load_profile(p)
    assert prof.salary_floor == 140000
    assert prof.locations.remote is True
    assert "web3" in prof.blocklist
    assert "I write Python." in prof.body


def test_profile_rejects_bad_salary_not_listed(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text(PROFILE.replace("salary_not_listed: keep", "salary_not_listed: maybe"))
    with pytest.raises(ValidationError):
        load_profile(p)


def test_profile_requires_frontmatter(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text("no frontmatter here")
    with pytest.raises(ValueError, match="frontmatter"):
        load_profile(p)


def test_load_pipeline_config(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE)
    cfg = load_pipeline_config(p)
    assert cfg.stages == ["dedup", "hard_filter"]
    assert cfg.models["score"] == "opus"
    assert cfg.limits.max_agent_jobs_per_run == 40


def test_pipeline_config_rejects_negative_cap(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE.replace("40", "-1"))
    with pytest.raises(ValidationError):
        load_pipeline_config(p)
