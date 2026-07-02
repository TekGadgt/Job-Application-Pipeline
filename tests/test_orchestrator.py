from datetime import datetime, UTC
from job_pipeline.core.job import Job
from job_pipeline.core.stage import StageSpec
from job_pipeline.core.orchestrator import DeterministicOrchestrator


def make_job(n):
    return Job(source="t", url=f"https://x.com/{n}", raw_text="", fetched_at=datetime.now(UTC))


class FakeStage:
    def __init__(self, name, kind="deterministic", action=None):
        self.spec = StageSpec(name, "test", [], [], kind, "free")
        self.action = action
        self.seen: list[str] = []

    def run(self, job):
        self.seen.append(job.id)
        if self.action:
            self.action(job)
        return job


def test_runs_stages_in_order_and_short_circuits_rejects():
    reject_all = FakeStage("a", action=lambda j: j.mark_rejected("a", "no"))
    after = FakeStage("b")
    result = DeterministicOrchestrator().run([make_job(1)], [reject_all, after])
    assert after.seen == []
    assert result.processed[0].rejected


def test_stage_exception_marks_errored_and_run_continues():
    def boom(job):
        raise ValueError("kapow")
    bad = FakeStage("bad", action=boom)
    j1, j2 = make_job(1), make_job(2)
    result = DeterministicOrchestrator().run([j1, j2], [bad])
    assert j1.errored and "kapow" in j1.error
    assert j2.errored          # both processed; neither killed the run


def test_agent_cap_defers_fifo():
    agent = FakeStage("agent", kind="agent")
    jobs = [make_job(i) for i in range(3)]
    result = DeterministicOrchestrator(max_agent_jobs=2).run(jobs, [agent])
    assert len(result.processed) == 2 and len(result.deferred) == 1
    assert result.deferred[0].id == jobs[2].id
    assert len(agent.seen) == 2


def test_rejected_jobs_do_not_consume_agent_cap():
    rejecter = FakeStage("r", action=lambda j: j.mark_rejected("r", "no"))
    agent = FakeStage("agent", kind="agent")
    jobs = [make_job(i) for i in range(3)]
    result = DeterministicOrchestrator(max_agent_jobs=1).run(jobs, [rejecter, agent])
    assert result.deferred == []          # nobody reached the agent stage


def test_errored_job_short_circuits_later_stages():
    def boom(job):
        raise ValueError("kapow")
    bad = FakeStage("bad", action=boom)
    after = FakeStage("after")
    DeterministicOrchestrator().run([make_job(1)], [bad, after])
    assert after.seen == []


def test_rerunning_same_jobs_does_not_corrupt_cap():
    agent = FakeStage("agent", kind="agent")
    jobs = [make_job(i) for i in range(2)]
    orch = DeterministicOrchestrator(max_agent_jobs=2)
    r1 = orch.run(jobs, [agent])
    r2 = orch.run(r1.processed, [agent])   # reuse the same Job objects
    assert len(r2.processed) == 2 and r2.deferred == []
