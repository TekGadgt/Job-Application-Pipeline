"""CLI wiring tests — run_pipeline is stubbed; no network, no tokens."""
from __future__ import annotations

import job_pipeline.cli as cli
from job_pipeline.sources.manual import ManualSource

PIPELINE = """
sources:
  - {type: rss, url: "https://example.com/feed"}
stages: [dedup, hard_filter]
models: {extract: haiku, skill_gap: sonnet, score: opus}
output: {vault: /tmp/vault}
"""

PROFILE = """---
salary_floor: 100000
---
Resume body.
"""


def _write_configs(tmp_path):
    cfg = tmp_path / "pipeline.yaml"
    prof = tmp_path / "profile.md"
    cfg.write_text(PIPELINE)
    prof.write_text(PROFILE)
    return cfg, prof


def _run(monkeypatch, tmp_path, extra_args):
    cfg, prof = _write_configs(tmp_path)
    captured = {}

    def fake_run_pipeline(*args, **kwargs):
        captured["args"], captured["kwargs"] = args, kwargs
        from job_pipeline.core.pipeline import RunSummary
        return RunSummary()

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)
    rc = cli.main(["run", "--config", str(cfg), "--profile", str(prof),
                   "--mock", *extra_args])
    assert rc == 0
    return captured


def test_url_flag_skips_configured_sources(monkeypatch, tmp_path):
    captured = _run(monkeypatch, tmp_path, ["--url", "https://example.com/job/1"])
    sources = captured["kwargs"]["sources"]
    assert len(sources) == 1
    assert isinstance(sources[0], ManualSource)
    assert sources[0].urls == ["https://example.com/job/1"]
    assert sources[0].inbox is None   # inbox is skipped too on a --url run


def test_no_url_flag_uses_configured_sources(monkeypatch, tmp_path):
    captured = _run(monkeypatch, tmp_path, [])
    assert captured["kwargs"]["sources"] is None   # run_pipeline builds from config


def test_reprocess_requires_url(tmp_path):
    import pytest
    cfg, prof = _write_configs(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["run", "--config", str(cfg), "--profile", str(prof),
                  "--mock", "--reprocess"])


def test_reprocess_clears_seen_row_before_run(monkeypatch, tmp_path):
    import hashlib
    from job_pipeline.store.seen_index import SeenIndex
    vault = tmp_path / "vault"
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text(
        "stages: [dedup]\n"
        f"output: {{vault: {vault}}}\n"
        "models: {extract: haiku, skill_gap: sonnet, score: opus}\n"
    )
    prof = tmp_path / "profile.md"
    prof.write_text(PROFILE)
    url = "https://example.com/job/1"
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    idx = SeenIndex(vault / ".job_pipeline.seen.sqlite")
    idx.mark(h)
    idx.close()

    def fake_run_pipeline(*args, **kwargs):
        from job_pipeline.core.pipeline import RunSummary
        return RunSummary()

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)
    rc = cli.main(["run", "--config", str(cfg), "--profile", str(prof),
                   "--mock", "--url", url, "--reprocess"])
    assert rc == 0
    assert not SeenIndex(vault / ".job_pipeline.seen.sqlite").has_url(h)
