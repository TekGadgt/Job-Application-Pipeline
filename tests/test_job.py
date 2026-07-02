from datetime import datetime, UTC
from job_pipeline.core.job import Job


def make_job(url="https://example.com/j/1"):
    return Job(source="test", url=url, raw_text="text", fetched_at=datetime.now(UTC))


def test_id_is_stable_hash_of_url():
    a, b = make_job(), make_job()
    assert a.id == b.id and len(a.id) == 16
    assert make_job("https://example.com/j/2").id != a.id


def test_mark_rejected_sets_verdict_and_trace():
    j = make_job()
    j.mark_rejected("hard_filter", "blocklist: web3")
    assert j.rejected and j.reject_stage == "hard_filter"
    assert j.reject_reason == "blocklist: web3"
    assert j.trace[-1][0] == "hard_filter" and j.trace[-1][1] == "rejected: blocklist: web3"


def test_mark_errored_is_distinct_from_rejected():
    j = make_job()
    j.mark_errored("extract", "boom")
    assert j.errored and not j.rejected and j.error == "boom"


def test_defaults():
    j = make_job()
    assert j.comp_min is None and j.salary_ok is None
    assert j.requirements == [] and j.skill_gap == {} and j.trace == []
