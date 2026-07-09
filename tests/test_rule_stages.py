from datetime import datetime, UTC
from job_pipeline.core.job import Job
from job_pipeline.config import Profile, LocationRules
from job_pipeline.store.seen_index import SeenIndex
from job_pipeline.stages.rules import (
    DedupStage, HardFilterStage, FuzzyDedupStage, LocationStage, SalaryStage,
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


def test_fuzzy_dedup_rejects_cross_source_duplicate(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("otherhash", "acme|engineer|remote")
    j = make_job(company="Acme", title="Engineer", location="Remote")
    out = FuzzyDedupStage(idx).run(j)
    assert out.rejected and out.reject_stage == "dedup_fuzzy"
    assert j.fuzzy_key == "acme|engineer|remote"


def test_fuzzy_dedup_passes_same_role_different_location(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("otherhash", "acme|engineer|remote")
    out = FuzzyDedupStage(idx).run(
        make_job(company="Acme", title="Engineer", location="New York, NY"))
    assert not out.rejected
    assert out.fuzzy_key == "acme|engineer|newyorkny"


def test_fuzzy_dedup_legacy_row_blocks_all_locations(tmp_path):
    # Rows written before location-aware keys hold the 2-part form and
    # keep blocking the role everywhere.
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("oldhash", "acme|engineer")
    out = FuzzyDedupStage(idx).run(
        make_job(company="Acme", title="Engineer", location="Berlin"))
    assert out.rejected and out.reject_stage == "dedup_fuzzy"


def test_fuzzy_dedup_no_key_when_company_and_title_empty(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    out = FuzzyDedupStage(idx).run(make_job(company="", title="", location="Remote"))
    assert not out.rejected
    assert out.fuzzy_key == ""


# --- location ---
def test_location_remote_ok_when_profile_allows_remote():
    p = profile(locations=LocationRules(remote=True, allowed_metros=[]))
    out = LocationStage(p).run(make_job(location="Remote (US)"))
    assert out.location_ok and not out.rejected


def test_location_rejects_disallowed_metro():
    p = profile(locations=LocationRules(remote=False, allowed_metros=["Richmond, VA"]))
    out = LocationStage(p).run(make_job(location="San Francisco, CA"))
    assert out.rejected and out.location_ok is False


def test_location_allows_listed_metro():
    p = profile(locations=LocationRules(remote=False, allowed_metros=["Richmond, VA"]))
    assert not LocationStage(p).run(make_job(location="Richmond, VA (hybrid)")).rejected


# --- salary ---
def test_salary_rejects_below_floor():
    p = profile(salary_floor=140000)
    out = SalaryStage(p).run(make_job(comp_max=120000, comp_period="annual"))
    assert out.rejected and out.salary_ok is False


def test_salary_passes_at_or_above_floor():
    p = profile(salary_floor=140000)
    assert not SalaryStage(p).run(make_job(comp_max=150000, comp_period="annual")).rejected


def test_salary_normalizes_hourly():
    p = profile(salary_floor=140000)
    # $80/hr * 2080 = 166,400 -> pass
    assert not SalaryStage(p).run(make_job(comp_max=80, comp_period="hourly")).rejected


def test_salary_not_listed_keep_vs_reject():
    keep = SalaryStage(profile(salary_floor=140000, salary_not_listed="keep"))
    rej = SalaryStage(profile(salary_floor=140000, salary_not_listed="reject"))
    kept = keep.run(make_job())
    assert not kept.rejected and kept.salary_ok is True
    assert rej.run(make_job()).rejected


def test_salary_no_floor_always_passes():
    assert not SalaryStage(profile()).run(make_job()).rejected


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
