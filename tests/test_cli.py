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
