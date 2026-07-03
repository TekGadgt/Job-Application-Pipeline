from job_pipeline.config import PipelineConfig, OutputConfig
from job_pipeline.core.pipeline import build_sources
from job_pipeline.sources.base import HintedSource
from job_pipeline.sources.feeds import RssSource


def _cfg(source_spec, tmp_path):
    return PipelineConfig(
        sources=[source_spec],
        stages=["dedup"],
        output=OutputConfig(vault=tmp_path / "vault"),
    )


def test_build_sources_wraps_and_pops_hint_key(tmp_path):
    # extract_hint must be popped before construction: RssSource(url=...) would
    # raise TypeError if handed an unexpected extract_hint kwarg.
    cfg = _cfg({"type": "rss", "url": "https://h/x.rss",
                "extract_hint": "free-form HN comment"}, tmp_path)
    sources = build_sources(cfg)
    assert len(sources) == 1
    assert isinstance(sources[0], HintedSource)
    assert isinstance(sources[0].inner, RssSource)
    assert sources[0].hint == "free-form HN comment"


def test_build_sources_leaves_source_bare_without_hint(tmp_path):
    cfg = _cfg({"type": "rss", "url": "https://h/x.rss"}, tmp_path)
    sources = build_sources(cfg)
    assert len(sources) == 1
    assert isinstance(sources[0], RssSource)      # not wrapped
