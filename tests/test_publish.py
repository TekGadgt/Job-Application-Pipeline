from datetime import datetime, UTC
import yaml
from job_pipeline.core.job import Job
from job_pipeline.store.obsidian import ObsidianWriter
from job_pipeline.stages.publish import PublishStage


def scored_job():
    j = Job(source="t", url="https://x.com/1", raw_text="", fetched_at=datetime.now(UTC),
            title="Senior Engineer", company="Acme Corp", location="Remote",
            comp_text="$150k-$180k", description="Build things.")
    j.score, j.score_rationale = 87.0, "Strong match"
    j.skill_gap = {"have": ["python"], "missing": ["rust"], "partial": []}
    return j


def read_frontmatter(path):
    _, fm, _ = path.read_text().split("---", 2)
    return yaml.safe_load(fm)


def test_write_creates_note_with_vec_frontmatter(tmp_path):
    w = ObsidianWriter(tmp_path)
    path = w.write(scored_job())
    fm = read_frontmatter(path)
    assert fm["company"] == "Acme Corp"
    assert fm["type_of_work"] == "Senior Engineer"
    assert fm["result_of_contact"] == "found"
    assert fm["date_of_contact"] == ""        # user fills on apply
    assert fm["status"] == "to_review"
    assert fm["score"] == 87.0
    body = path.read_text()
    assert "Strong match" in body and "rust" in body


def test_publish_skips_user_touched_note(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    path = w.write(j)
    path.write_text(path.read_text().replace("status: to_review", "status: applied"))
    j2 = scored_job()
    j2.score_rationale = "CHANGED"
    PublishStage(w).run(j2)
    assert "CHANGED" not in path.read_text()   # user's edit protected


def test_publish_force_overwrites(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    path = w.write(j)
    path.write_text(path.read_text().replace("status: to_review", "status: applied"))
    j2 = scored_job()
    j2.score_rationale = "CHANGED"
    PublishStage(w, force=True).run(j2)
    assert "CHANGED" in path.read_text()


def test_publish_stage_traces(tmp_path):
    j = PublishStage(ObsidianWriter(tmp_path)).run(scored_job())
    assert j.trace[-1][0] == "publish"


def comp_job(**kw):
    j = scored_job()
    j.comp_text = kw.pop("comp_text", "")
    for k, v in kw.items():
        setattr(j, k, v)
    return j


# --- format_comp ---
def test_format_comp_range_annual():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=150000, comp_max=180000, comp_currency="USD", comp_period="annual")
    assert format_comp(j) == "$150,000–$180,000 USD (annual)"


def test_format_comp_single_value():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=150000, comp_max=150000, comp_currency="USD", comp_period="annual")
    assert format_comp(j) == "$150,000 USD (annual)"


def test_format_comp_hourly_annualizes():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=35, comp_max=40, comp_currency="USD", comp_period="hourly")
    assert format_comp(j) == "$35–$40 USD/hr (≈ $72,800–$83,200 annualized)"


def test_format_comp_non_usd_no_dollar_sign():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=150000, comp_max=180000, comp_currency="EUR", comp_period="annual")
    assert format_comp(j) == "150,000–180,000 EUR (annual)"


def test_format_comp_not_listed():
    from job_pipeline.store.obsidian import format_comp
    assert format_comp(comp_job()) == "Not listed"


def test_format_comp_not_listed_with_text():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_text="competitive + equity")
    assert format_comp(j) == 'Not listed — listed text: "competitive + equity"'


def test_format_comp_provenance_appended_when_text_present():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=150000, comp_max=180000, comp_currency="USD",
                 comp_period="annual", comp_text="$150k-$180k")
    assert format_comp(j) == '$150,000–$180,000 USD (annual) (listed as "$150k-$180k")'


# --- new frontmatter schema ---
BINDING_ORDER = [
    "company", "position", "location", "employer_address", "employer_phone",
    "employer_email", "employer_contact_person", "date_found", "date_of_contact",
    "source_url", "type_of_work", "result_of_contact", "application_status",
    "score", "comp_min", "comp_max", "comp_currency", "comp_period",
    "status", "job_id", "role_key", "possible_duplicate",
]


def test_frontmatter_matches_binding_order_and_new_keys(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    j.comp_min, j.comp_max = 150000, 180000
    j.comp_currency, j.comp_period = "USD", "annual"
    j.fuzzy_key = "acmecorp|seniorengineer|remote"
    path = w.write(j)
    fm = read_frontmatter(path)
    assert list(fm.keys()) == BINDING_ORDER
    assert fm["location"] == "Remote"
    assert fm["comp_min"] == 150000 and fm["comp_max"] == 180000
    assert fm["application_status"] == "Unsubmitted"
    assert fm["role_key"] == "acmecorp|seniorengineer|remote"
    assert fm["possible_duplicate"] is False


def test_frontmatter_nulls_when_absent(tmp_path):
    w = ObsidianWriter(tmp_path)
    path = w.write(scored_job())    # no comp numbers, no fuzzy key
    fm = read_frontmatter(path)
    assert fm["comp_min"] is None and fm["comp_max"] is None
    assert fm["comp_currency"] is None and fm["comp_period"] is None
    assert fm["role_key"] is None


def test_possible_duplicate_true_from_trace(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    j.fuzzy_key = "acmecorp|seniorengineer|remote"
    j.add_trace("dedup_fuzzy", "possible duplicate: acmecorp|seniorengineer|remote")
    fm = read_frontmatter(w.write(j))
    assert fm["possible_duplicate"] is True


def test_body_has_compensation_section_in_order(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    j.comp_min = j.comp_max = 150000
    j.comp_currency, j.comp_period = "USD", "annual"
    text = w.write(j).read_text()
    fit = text.index("## Fit")
    comp = text.index("## Compensation")
    gap = text.index("## Skill gap")
    desc = text.index("## Description")
    assert fit < comp < gap < desc
    assert "$150,000 USD (annual)" in text


# --- skip-on-edit extension ---
def test_user_touched_when_application_status_advanced(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    path = w.write(j)
    path.write_text(path.read_text().replace(
        "application_status: Unsubmitted", "application_status: Submitted"))
    assert w.is_user_touched(j)


def test_not_touched_when_fresh(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    w.write(j)
    assert not w.is_user_touched(j)


def test_legacy_note_without_application_status_uses_status_only(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    path = w.write(j)
    # simulate a pre-feature note: drop the application_status line entirely
    path.write_text(path.read_text().replace("application_status: Unsubmitted\n", ""))
    assert not w.is_user_touched(j)


def test_malformed_yaml_frontmatter_treated_as_user_owned(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    path = w.write(j)
    path.write_text("---\nbad: [oops\n---\nbody\n")
    assert w.is_user_touched(j)   # must not raise
