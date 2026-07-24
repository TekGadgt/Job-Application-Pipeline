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

IMPORT_BLOCK = """
import:
  path: /tmp/old-tracker
  fields:
    company: company
    position: position
    application_status: status
    date_of_contact: date-applied
    source_url: website
  keep_unmapped: true
"""


def test_load_profile_parses_frontmatter_and_body(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text(PROFILE)
    prof = load_profile(p)
    assert "web3" in prof.blocklist
    assert "I write Python." in prof.body
    # keys removed in the 2026-07-23 lean re-cut load inert, not as errors
    for dead in ("salary_floor", "locations", "must_have_skills",
                 "nice_to_have", "salary_not_listed"):
        assert not hasattr(prof, dead)


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
    assert not hasattr(cfg.output, "keep_rejects")   # retired dead config


def test_pipeline_config_rejects_negative_cap(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE.replace("40", "-1"))
    with pytest.raises(ValidationError):
        load_pipeline_config(p)


def test_profile_body_may_contain_horizontal_rules(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text(PROFILE + "\n---\n\nMore resume text after a rule.")
    prof = load_profile(p)
    assert "More resume text after a rule." in prof.body


def test_profile_unclosed_frontmatter_raises_clear_error(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text("---\nsalary_floor: 1\nno closing delimiter")
    with pytest.raises(ValueError, match="frontmatter"):
        load_profile(p)


def test_pipeline_config_treats_commented_out_sections_as_empty(tmp_path):
    # yaml parses a key with all entries commented out as None, not []
    p = tmp_path / "pipeline.yaml"
    p.write_text(
        "sources:\n"
        "#  - {type: rss, url: 'https://example.com/feed'}\n"
        "seeders:\n"
        "#  - {type: existing_vault, path: /tmp/vault}\n"
        "models:\n"
        "stages: [dedup]\n"
        "output: {vault: /tmp/vault}\n"
    )
    cfg = load_pipeline_config(p)
    assert cfg.sources == []
    assert cfg.seeders == []
    assert cfg.models == {}


def test_import_block_parses(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE + IMPORT_BLOCK)
    cfg = load_pipeline_config(p)
    assert cfg.import_ is not None
    assert cfg.import_.fields["application_status"] == "status"
    assert cfg.import_.keep_unmapped is True


def test_import_block_absent_is_none(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE)
    assert load_pipeline_config(p).import_ is None


def test_import_unknown_canonical_fails_naming_key(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE + IMPORT_BLOCK.replace("company: company", "bogus: company"))
    with pytest.raises(ValidationError, match="bogus"):
        load_pipeline_config(p)
