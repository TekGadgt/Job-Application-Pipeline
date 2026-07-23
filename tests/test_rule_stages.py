from datetime import datetime, UTC
from job_pipeline.core.job import Job
from job_pipeline.config import Profile
from job_pipeline.store.seen_index import SeenIndex
from job_pipeline.stages.rules import (
    DedupStage, HardFilterStage, FuzzyDedupStage,
    make_fuzzy_key,
)


def make_job(**kw):
    base = dict(source="t", url="https://x.com/1", raw_text="", fetched_at=datetime.now(UTC))
    base.update(kw)
    return Job(**base)


def profile(**kw):
    return Profile(**kw)


# --- dedup ---
def test_dedup_rejects_seen_url(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    j = make_job()
    idx.mark(j.id)
    out = DedupStage(idx).run(make_job())
    assert out.rejected and out.reject_stage == "dedup"


def test_dedup_passes_unseen(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    assert not DedupStage(idx).run(make_job()).rejected


# --- hard filter ---
def test_hard_filter_matches_word_boundary_case_insensitive():
    p = profile(blocklist=["web3", "crypto"])
    st = HardFilterStage(p)
    assert st.run(make_job(raw_text="Exciting Web3 startup!")).rejected
    assert not st.run(make_job(raw_text="cryptography experience a plus")).rejected


def test_hard_filter_records_which_keyword():
    p = profile(blocklist=["defi"])
    out = HardFilterStage(p).run(make_job(raw_text="DeFi protocols"))
    assert "defi" in out.reject_reason


# --- fuzzy key + fuzzy dedup ---
def test_make_fuzzy_key_normalizes():
    assert make_fuzzy_key("Acme, Inc.", "Sr. Engineer") == "acmeinc|srengineer|"
    assert make_fuzzy_key("Acme, Inc.", "Sr. Engineer", "Remote (US)") == "acmeinc|srengineer|remoteus"


def test_legacy_fuzzy_key_is_two_part():
    from job_pipeline.stages.rules import legacy_fuzzy_key
    assert legacy_fuzzy_key("Acme, Inc.", "Sr. Engineer") == "acmeinc|srengineer"


def test_fuzzy_dedup_flags_cross_source_duplicate_but_passes(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("otherhash", "acme|engineer|remote")
    j = make_job(company="Acme", title="Engineer", location="Remote")
    out = FuzzyDedupStage(idx).run(j)
    assert not out.rejected
    assert out.fuzzy_key == "acme|engineer|remote"
    assert any("possible duplicate: acme|engineer|remote" in verdict
               for _, verdict, _ in out.trace)


def test_fuzzy_dedup_passes_same_role_different_location(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("otherhash", "acme|engineer|remote")
    out = FuzzyDedupStage(idx).run(
        make_job(company="Acme", title="Engineer", location="New York, NY"))
    assert not out.rejected
    assert out.fuzzy_key == "acme|engineer|newyorkny"


def test_fuzzy_dedup_legacy_row_flags_all_locations(tmp_path):
    # Rows written before location-aware keys hold the 2-part form and
    # still flag the role everywhere — but no longer reject it.
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("oldhash", "acme|engineer")
    out = FuzzyDedupStage(idx).run(
        make_job(company="Acme", title="Engineer", location="Berlin"))
    assert not out.rejected
    # the trace names the key that actually matched, not the 3-part probe
    assert any("possible duplicate: acme|engineer (legacy pre-location match)" in verdict
               for _, verdict, _ in out.trace)


def test_fuzzy_dedup_no_key_when_company_and_title_empty(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    out = FuzzyDedupStage(idx).run(make_job(company="", title="", location="Remote"))
    assert not out.rejected
    assert out.fuzzy_key == ""


# --- score floor ---
def test_score_floor_rejects_below_floor():
    from job_pipeline.stages.rules import ScoreFloorStage
    out = ScoreFloorStage(profile(score_floor=60)).run(make_job(score=42.0))
    assert out.rejected and out.reject_stage == "score_floor"
    assert "42.0" in out.reject_reason and "60" in out.reject_reason


def test_score_floor_boundary_is_inclusive_keep():
    from job_pipeline.stages.rules import ScoreFloorStage
    assert not ScoreFloorStage(profile(score_floor=60)).run(make_job(score=60.0)).rejected


def test_score_floor_no_floor_passes():
    from job_pipeline.stages.rules import ScoreFloorStage
    assert not ScoreFloorStage(profile()).run(make_job(score=1.0)).rejected


def test_score_floor_no_score_passes_with_trace():
    from job_pipeline.stages.rules import ScoreFloorStage
    out = ScoreFloorStage(profile(score_floor=60)).run(make_job())
    assert not out.rejected
    assert any("no score present" in verdict for _, verdict, _ in out.trace)


# --- lean re-cut: gates are gone ---
def test_location_and_salary_stages_are_gone():
    import pytest
    from job_pipeline.core.registry import get_stage
    for name in ("location", "salary"):
        with pytest.raises(KeyError):
            get_stage(name)
