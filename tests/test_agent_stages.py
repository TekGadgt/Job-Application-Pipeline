from datetime import datetime, UTC
from job_pipeline.core.job import Job
from job_pipeline.core.runner import MockRunner
from job_pipeline.config import Profile
from job_pipeline.stages.agents import ExtractStage, SkillGapStage, ScoreStage


def make_job(**kw):
    base = dict(source="t", url="https://x.com/1",
                raw_text="Senior Eng at Acme. $150k-$180k. Python required.",
                fetched_at=datetime.now(UTC))
    base.update(kw)
    return Job(**base)


EXTRACT_REPLY = {
    "title": "Senior Engineer", "company": "Acme", "location": "Remote",
    "comp_text": "$150k-$180k", "comp_min": 150000, "comp_max": 180000,
    "comp_currency": "USD", "comp_period": "annual",
    "requirements": ["python"], "description": "Build things.",
}


def test_extract_maps_reply_onto_job():
    r = MockRunner([EXTRACT_REPLY])
    j = ExtractStage(r, "haiku").run(make_job())
    assert j.company == "Acme" and j.comp_max == 180000
    assert not j.rejected
    prompt, model = r.calls[0]
    assert model == "haiku" and "Senior Eng at Acme" in prompt


def test_skill_gap_stores_dict_and_reads_profile():
    p = Profile(must_have_skills=["python"], body="## Resume\nPython dev")
    r = MockRunner([{"have": ["python"], "missing": ["rust"], "partial": []}])
    j = SkillGapStage(r, "sonnet", p).run(make_job(requirements=["python", "rust"]))
    assert j.skill_gap == {"have": ["python"], "missing": ["rust"], "partial": []}
    assert "Python dev" in r.calls[0][0]      # resume body fed to the agent


def test_score_sets_score_and_rationale():
    p = Profile(body="prefs")
    r = MockRunner([{"score": 87.0, "rationale": "Strong match"}])
    j = ScoreStage(r, "opus", p).run(make_job())
    assert j.score == 87.0 and j.score_rationale == "Strong match"
    assert r.calls[0][1] == "opus"


def test_extract_tolerates_braces_in_raw_text():
    r = MockRunner([EXTRACT_REPLY])
    j = ExtractStage(r, "haiku").run(
        make_job(raw_text='<script type="application/ld+json">{"@type": "JobPosting"}</script>')
    )
    assert j.company == "Acme"
    assert '{"@type": "JobPosting"}' in r.calls[0][0]


def test_fill_does_not_resubstitute_placeholders_inside_values():
    from job_pipeline.stages.agents import _fill
    # A malicious/unlucky listing containing a placeholder token must not
    # have other values (e.g. the resume) substituted into it.
    out = _fill("A: {a}\nB: {b}", a="contains {b} literally", b="RESUME")
    assert out == "A: contains {b} literally\nB: RESUME"


def test_fill_leaves_json_braces_and_unknown_tokens_intact():
    from job_pipeline.stages.agents import _fill
    template = 'Reply with {"title": str}\nX: {known} Y: {unknown}'
    out = _fill(template, known="v")
    assert out == 'Reply with {"title": str}\nX: v Y: {unknown}'


def test_extract_prepends_source_context_when_hint_present():
    r = MockRunner([EXTRACT_REPLY])
    # Hint contains a brace token to pin brace-safe composition (verbatim, no splice).
    ExtractStage(r, "haiku").run(make_job(extract_hint="HN comment; fields like {company}"))
    prompt = r.calls[0][0]
    assert prompt.startswith("SOURCE CONTEXT: HN comment; fields like {company}\n\n")
    assert "Senior Eng at Acme" in prompt        # raw_text still present


def test_extract_omits_source_context_when_no_hint():
    r = MockRunner([EXTRACT_REPLY])
    ExtractStage(r, "haiku").run(make_job())      # no hint
    prompt = r.calls[0][0]
    assert "SOURCE CONTEXT" not in prompt
    assert prompt.startswith("Extract structured fields from this job listing.")
