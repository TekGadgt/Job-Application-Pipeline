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


VENDOR_ROOTS = [
    "https://www.icims.com", "https://www.bamboohr.com", "https://www.taleo.net",
    "https://www.teamtailor.com", "https://www.eightfold.ai", "https://www.breezy.hr",
    "https://www.recruitee.com", "https://www.oraclecloud.com",
]


@pytest.mark.parametrize("url", VENDOR_ROOTS)
def test_detect_rejects_vendor_marketing_roots(url):
    assert detect(url) is None


def test_detect_rejects_lookalike_and_unqualified_urls():
    assert detect("https://myboards.greenhouse.io/exampleco") is None
    assert detect("https://exampleco.oraclecloud.com/some/erp/app") is None
    assert detect("https://exampleco.bamboohr.com/") is None


def test_detect_greenhouse_embed_prefers_for_query_param():
    # FINDING 2: embed/job_app URLs must not register the reserved segment
    # ("embed"/"job_app"/"job_board") as the company slug.
    assert detect(
        "https://boards.greenhouse.io/embed/job_app?token=1&for=acme"
    ) == ("greenhouse", "acme")


def test_detect_greenhouse_embed_without_for_param_is_none():
    assert detect("https://boards.greenhouse.io/embed/job_app?token=1") is None


def test_detect_greenhouse_embed_for_param_is_url_decoded():
    # FINDING 3: for= is a raw query-string value and may be percent-encoded.
    assert detect(
        "https://boards.greenhouse.io/embed/job_app?token=1&for=Acme%20Inc"
    ) == ("greenhouse", "Acme Inc")


def test_detect_greenhouse_embed_for_param_is_case_insensitive():
    # FINDING 3: query param names are conventionally case-insensitive.
    assert detect(
        "https://boards.greenhouse.io/embed/job_app?token=1&FOR=acme"
    ) == ("greenhouse", "acme")


def test_detect_eightfold_is_path_qualified():
    # FINDING 4: eightfold must require /careers, like oraclecloud/bamboohr.
    assert detect("https://exampleco.eightfold.ai/careers") == ("eightfold", "exampleco")
    assert detect("https://blog.eightfold.ai/post/1") is None
    assert detect("https://resources.eightfold.ai/x") is None
