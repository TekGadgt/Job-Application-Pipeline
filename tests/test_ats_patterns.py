import pytest
from job_pipeline.ats_patterns import detect

CASES = [
    ("https://boards.greenhouse.io/exampleco/jobs/123", ("greenhouse", "exampleco")),
    ("https://job-boards.greenhouse.io/exampleco", ("greenhouse", "exampleco")),
    ("https://jobs.lever.co/exampleco/abc-123", ("lever", "exampleco")),
    ("https://jobs.ashbyhq.com/exampleco/posting-id", ("ashby", "exampleco")),
    ("https://careers.smartrecruiters.com/ExampleCo", ("smartrecruiters", "ExampleCo")),
    ("https://exampleco.wd5.myworkdayjobs.com/en-US/careers", ("workday", "exampleco")),
    ("https://careers-exampleco.icims.com/jobs/123", ("icims", "careers-exampleco")),
    ("https://exampleco.taleo.net/careersection/x", ("taleo", "exampleco")),
    ("https://exampleco.bamboohr.com/careers/42", ("bamboohr", "exampleco")),
    ("https://apply.workable.com/exampleco/", ("workable", "exampleco")),
    ("https://jobs.jobvite.com/exampleco/job/x", ("jobvite", "exampleco")),
    ("https://exampleco.eightfold.ai/careers", ("eightfold", "exampleco")),
    ("https://exampleco.teamtailor.com/jobs", ("teamtailor", "exampleco")),
    ("https://exampleco.breezy.hr/p/abc", ("breezy", "exampleco")),
    ("https://exampleco.recruitee.com/o/role", ("recruitee", "exampleco")),
    ("https://recruiting.ultipro.com/COL1030CWF/JobBoard/d1d83d8e-bd7f/OpportunityDetail?opportunityId=x",
     ("ultipro", "COL1030CWF")),
    ("https://exampleco.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX", ("oraclecloud", "exampleco")),
]


@pytest.mark.parametrize("url,expected", CASES)
def test_detect_known_platforms(url, expected):
    assert detect(url) == expected


def test_detect_unknown_returns_none():
    assert detect("https://example.com/careers") is None
    assert detect("not a url") is None
