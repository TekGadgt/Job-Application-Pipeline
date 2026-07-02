from datetime import datetime, UTC
from pathlib import Path
from job_pipeline.config import Profile, PipelineConfig, OutputConfig, Limits, LocationRules
from job_pipeline.core.job import Job
from job_pipeline.core.runner import MockRunner
from job_pipeline.core.pipeline import run_pipeline


class FakeSource:
    def __init__(self, jobs):
        self.jobs = jobs
        self.terminal: list[str] = []
    def fetch(self):
        return self.jobs
    def on_terminal(self, job):
        self.terminal.append(job.url)


def make_cfg(tmp_path):
    return PipelineConfig(
        stages=["dedup", "hard_filter", "extract", "dedup_fuzzy",
                "location", "salary", "skill_gap", "score", "publish"],
        models={"extract": "haiku", "skill_gap": "sonnet", "score": "opus"},
        output=OutputConfig(vault=tmp_path / "vault"),
        limits=Limits(max_agent_jobs_per_run=10),
    )


def make_profile():
    return Profile(salary_floor=100000, blocklist=["web3"],
                   locations=LocationRules(remote=True), body="Python dev")


def job(url, text):
    return Job(source="fake", url=url, raw_text=text, fetched_at=datetime.now(UTC))


def test_full_run_publishes_good_job_and_rejects_blocked(tmp_path):
    good = job("https://x.com/good", "Senior Python Engineer at Acme, remote, $150k")
    bad = job("https://x.com/bad", "web3 wizard needed")
    src = FakeSource([good, bad])
    runner = MockRunner([
        {"title": "Senior Engineer", "company": "Acme", "location": "Remote",
         "comp_text": "$150k", "comp_min": 150000, "comp_max": 150000,
         "comp_currency": "USD", "comp_period": "annual",
         "requirements": ["python"], "description": "Build."},
        {"have": ["python"], "missing": [], "partial": []},
        {"score": 90.0, "rationale": "great"},
    ])
    summary = run_pipeline(
        make_cfg(tmp_path), make_profile(), runner,
        sources=[src], db_path=tmp_path / "seen.sqlite",
    )
    assert summary.published == 1 and summary.rejected == 1
    assert len(summary.notes) == 1 and summary.notes[0].exists()
    # both terminal jobs reported back to their source (inbox consumption)
    assert set(src.terminal) == {"https://x.com/good", "https://x.com/bad"}


def test_second_run_dedups_everything(tmp_path):
    cfg, prof = make_cfg(tmp_path), make_profile()
    db = tmp_path / "seen.sqlite"
    replies = [
        {"title": "T", "company": "C", "location": "Remote", "comp_text": "",
         "comp_min": None, "comp_max": None, "comp_currency": None,
         "comp_period": None, "requirements": [], "description": "d"},
        {"have": [], "missing": [], "partial": []},
        {"score": 50.0, "rationale": "ok"},
    ]
    src1 = FakeSource([job("https://x.com/1", "listing")])
    run_pipeline(cfg, prof, MockRunner(replies), sources=[src1], db_path=db)
    src2 = FakeSource([job("https://x.com/1", "listing")])
    summary = run_pipeline(cfg, prof, MockRunner([]), sources=[src2], db_path=db)
    assert summary.rejected == 1 and summary.published == 0   # dedup, zero agent calls
