import json
from pathlib import Path
from job_pipeline.sources.manual import ManualSource
from job_pipeline.sources.feeds import RssSource, GreenhouseSource, LeverSource

FIX = Path(__file__).parent / "fixtures"


def test_rss_source_yields_job_per_entry():
    src = RssSource(url="ignored")
    src._get = lambda url: (FIX / "jobs.rss").read_text()
    jobs = src.fetch()
    assert len(jobs) == 2
    assert jobs[0].url == "https://example.com/jobs/1"
    assert "Python backend" in jobs[0].raw_text
    assert jobs[0].source == "rss"


def test_greenhouse_source_parses_board_json():
    src = GreenhouseSource(board="acme")
    src._get = lambda url: json.loads((FIX / "greenhouse.json").read_text())
    jobs = src.fetch()
    assert jobs[0].title == "Platform Engineer" and jobs[0].location == "Remote"
    assert "Python required" in jobs[0].raw_text


def test_lever_source_parses_postings():
    src = LeverSource(org="acme")
    src._get = lambda url: json.loads((FIX / "lever.json").read_text())
    jobs = src.fetch()
    assert jobs[0].title == "SRE" and jobs[0].location == "Richmond, VA"


def test_manual_source_reads_inbox_and_cli_urls(tmp_path):
    inbox = tmp_path / "inbox.txt"
    inbox.write_text("https://a.com/1\n\nhttps://a.com/2\n")
    src = ManualSource(inbox=inbox, urls=["https://b.com/3"])
    src._get = lambda url: f"page text for {url}"
    jobs = src.fetch()
    assert [j.url for j in jobs] == ["https://a.com/1", "https://a.com/2", "https://b.com/3"]


def test_manual_inbox_consumed_only_on_terminal(tmp_path):
    inbox = tmp_path / "inbox.txt"
    inbox.write_text("https://a.com/1\nhttps://a.com/2\n")
    src = ManualSource(inbox=inbox, urls=[])
    src._get = lambda url: "text"
    jobs = src.fetch()
    src.on_terminal(jobs[0])                       # published or rejected
    remaining = inbox.read_text().strip().splitlines()
    assert remaining == ["https://a.com/2"]        # errored line stays


def test_manual_fetch_error_marks_job_errored(tmp_path):
    src = ManualSource(inbox=None, urls=["https://dead.example"])
    def boom(url):
        raise OSError("connection refused")
    src._get = boom
    jobs = src.fetch()
    assert jobs[0].errored and "connection refused" in jobs[0].error


def test_on_terminal_never_removes_errored_job_line(tmp_path):
    inbox = tmp_path / "inbox.txt"
    inbox.write_text("https://a.com/1\n")
    src = ManualSource(inbox=inbox, urls=[])
    def boom(url):
        raise OSError("dead")
    src._get = boom
    jobs = src.fetch()
    src.on_terminal(jobs[0])                 # errored — must be a no-op
    assert inbox.read_text().strip() == "https://a.com/1"


def test_second_fetch_does_not_orphan_prior_inbox_jobs(tmp_path):
    inbox = tmp_path / "inbox.txt"
    inbox.write_text("https://a.com/1\n")
    src = ManualSource(inbox=inbox, urls=[])
    src._get = lambda url: "text"
    first = src.fetch()
    inbox.write_text("https://a.com/1\nhttps://a.com/2\n")
    src.fetch()
    src.on_terminal(first[0])                # from the FIRST fetch
    assert inbox.read_text().strip() == "https://a.com/2"
