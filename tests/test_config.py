import json

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


COMPANIES = """[
  {"name": "OldCo", "ats_platform": "greenhouse", "slug": "oldco",
   "notes": "marketplace, Vue stack", "source": "claude_research_batch_1"},
  {"name": "Disabled Inc", "ats_platform": "lever", "slug": "disabledinc", "enabled": false},
  {"no_name": "broken entry"}
]"""


def test_load_companies_tolerant(tmp_path, caplog):
    from job_pipeline.config import load_companies
    p = tmp_path / "companies.json"
    p.write_text(COMPANIES)
    entries = load_companies(p)
    assert [e.name for e in entries] == ["OldCo", "Disabled Inc"]   # bad entry skipped
    assert entries[0].enabled is True                                # default
    assert entries[1].enabled is False
    assert "skipping" in caplog.text.lower()


def test_load_companies_missing_file_warns_empty(tmp_path, caplog):
    from job_pipeline.config import load_companies
    assert load_companies(tmp_path / "nope.json") == []
    assert "nope.json" in caplog.text


def test_save_companies_round_trips(tmp_path):
    from job_pipeline.config import CompanyEntry, load_companies, save_companies
    p = tmp_path / "companies.json"
    save_companies(p, [CompanyEntry(name="A", ats_platform="lever", slug="a")])
    entries = load_companies(p)
    assert entries[0].slug == "a"


def test_load_companies_corrupt_file_warns_empty(tmp_path, caplog):
    import logging
    from job_pipeline.config import load_companies
    caplog.set_level(logging.WARNING, logger="job_pipeline")
    p = tmp_path / "companies.json"
    p.write_text('[{"name": "truncated"')
    assert load_companies(p) == []
    assert "unreadable" in caplog.text.lower() or "invalid" in caplog.text.lower()


def test_load_companies_non_list_warns_empty(tmp_path, caplog):
    import logging
    from job_pipeline.config import load_companies
    caplog.set_level(logging.WARNING, logger="job_pipeline")
    p = tmp_path / "companies.json"
    p.write_text('{"name": "not a list"}')
    assert load_companies(p) == []
    assert "list" in caplog.text.lower()


def test_load_save_round_trip_preserves_extra_keys_and_unparsable_entries(tmp_path):
    """FINDING 1: save_companies must not silently destroy data.

    Extra keys on a valid entry must round-trip (CompanyEntry allows extra),
    and an entry the loader could not parse at all must still be present in
    the file after a load -> save cycle (carried forward verbatim).
    """
    from job_pipeline.config import load_companies, save_companies

    p = tmp_path / "companies.json"
    p.write_text(json.dumps([
        {"name": "GoodCo", "ats_platform": "greenhouse", "slug": "goodco", "priority": 1},
        {"no_name": True},
    ]))
    entries = load_companies(p)
    assert len(entries) == 1   # only the valid entry parses
    save_companies(p, entries)

    saved = json.loads(p.read_text())
    assert len(saved) == 2
    good = next(e for e in saved if e.get("name") == "GoodCo")
    assert good["priority"] == 1                      # extra key round-tripped
    invalid = next(e for e in saved if e.get("no_name") is True)
    assert invalid == {"no_name": True}                # unparsable entry preserved verbatim


def test_save_companies_ignores_non_list_existing_file(tmp_path):
    """FINDING 2: the preservation re-read must guard non-list registry files.

    load_companies() already refuses (with a warning) to treat a dict-shaped
    file as a registry. save_companies()'s re-read-to-preserve-unparsable-
    entries loop must apply the same guard: without it, iterating a dict
    walks its *keys* and writes bare strings into `unparsed`, violating the
    `unparsed: list[dict]` contract and corrupting the output file.
    """
    from job_pipeline.config import CompanyEntry, save_companies

    p = tmp_path / "companies.json"
    p.write_text(json.dumps({"name": "not a list", "other": "also not a list"}))

    save_companies(p, [CompanyEntry(name="A", ats_platform="lever", slug="a")])

    saved = json.loads(p.read_text())
    assert saved == [
        CompanyEntry(name="A", ats_platform="lever", slug="a").model_dump(exclude_none=False)
    ]
    assert all(isinstance(e, dict) for e in saved)   # no bare strings from dict keys


def test_save_companies_drops_non_dict_entries(tmp_path, caplog):
    import logging
    from job_pipeline.config import load_companies, save_companies
    caplog.set_level(logging.WARNING, logger="job_pipeline")
    p = tmp_path / "companies.json"
    # valid list, but with stray non-object elements mixed in
    p.write_text('[{"name": "Good"}, "stray string", 42, {"no_name": true}]')
    save_companies(p, load_companies(p))
    saved = json.loads(p.read_text())
    assert all(isinstance(e, dict) for e in saved)      # schema never violated
    assert {"no_name": True} in saved                   # dict-shaped unparseable still preserved
    assert [e for e in saved if e.get("name") == "Good"]
    assert "non-object entry" in caplog.text


def test_company_contacts_field_defaults_null_and_round_trips(tmp_path):
    from job_pipeline.config import CompanyEntry, load_companies, save_companies
    p = tmp_path / "companies.json"
    save_companies(p, [
        CompanyEntry(name="NoContacts"),
        CompanyEntry(name="HasContacts", contacts=["Jane Doe — Staff Engineer"]),
    ])
    saved = json.loads(p.read_text())
    assert saved[0]["contacts"] is None                     # null by default
    assert saved[1]["contacts"] == ["Jane Doe — Staff Engineer"]
    assert load_companies(p)[1].contacts == ["Jane Doe — Staff Engineer"]


def test_load_companies_binary_file_warns_empty(tmp_path, caplog):
    import logging
    from job_pipeline.config import load_companies
    caplog.set_level(logging.WARNING, logger="job_pipeline")
    p = tmp_path / "companies.json"
    p.write_bytes(b"\xff\xfe\x00not utf-8 at all")
    assert load_companies(p) == []          # must not raise UnicodeDecodeError
    assert "invalid/unreadable" in caplog.text


def test_save_companies_survives_binary_existing_registry(tmp_path):
    """UnicodeDecodeError subclasses ValueError, which the preservation
    try/except already catches — pin it so narrowing that clause fails loudly."""
    from job_pipeline.config import CompanyEntry, load_companies, save_companies
    p = tmp_path / "companies.json"
    p.write_bytes(b"\xff\xfe\x00binary garbage not utf-8")
    save_companies(p, [CompanyEntry(name="NewCo", slug="newco", ats_platform="lever")])
    assert load_companies(p)[0].name == "NewCo"   # write went through, nothing raised
