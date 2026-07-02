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
