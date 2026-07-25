import json
from datetime import datetime, UTC
from job_pipeline.core.job import Job
from job_pipeline.sources.companies import CompaniesSource

REGISTRY = [
    {"name": "Good Co", "ats_platform": "greenhouse", "slug": "goodco",
     "notes": "great fit", "enabled": True},
    {"name": "Off Co", "ats_platform": "greenhouse", "slug": "offco", "enabled": False},
    {"name": "Banned Co", "ats_platform": "workable", "slug": "bannedco", "enabled": True},
    {"name": "Later Co", "ats_platform": "eightfold", "slug": "laterco", "enabled": True},
    {"name": "Slugless Co", "ats_platform": None, "slug": None,
     "careers_url": "https://jobs.lever.co/slugless/abc", "enabled": True},
]


class FakeATS:
    def __init__(self, jobs):
        self._jobs = jobs
    def fetch(self):
        return list(self._jobs)
    def on_terminal(self, job):
        pass


def make_registry(tmp_path, entries=REGISTRY):
    p = tmp_path / "companies.json"
    p.write_text(json.dumps(entries))
    return p


def job(url):
    return Job(source="greenhouse", url=url, raw_text="x", fetched_at=datetime.now(UTC))


def test_expands_enabled_supported_entries_with_company_override(tmp_path):
    p = make_registry(tmp_path)
    fetched = {}
    def make(ats, slug):
        fetched[(ats, slug)] = True
        return FakeATS([job(f"https://x.com/{slug}/1")])
    src = CompaniesSource(file=p, make=make)
    jobs = src.fetch()
    urls = {j.url for j in jobs}
    assert "https://x.com/goodco/1" in urls
    assert ("greenhouse", "offco") not in fetched          # disabled skipped
    assert ("workable", "bannedco") not in fetched         # banned refused
    assert ("eightfold", "laterco") not in fetched         # unsupported counted, not fetched
    good = next(j for j in jobs if "goodco" in j.url)
    assert good.company == "Good Co"                       # registry name wins over slug
    assert good.company_context == "great fit"


def test_resolves_and_persists_slug_from_careers_url(tmp_path):
    p = make_registry(tmp_path)
    src = CompaniesSource(file=p, make=lambda ats, slug: FakeATS([job(f"https://x.com/{slug}/1")]))
    src.fetch()
    saved = json.loads(p.read_text())
    slugless = next(e for e in saved if e["name"] == "Slugless Co")
    assert slugless["ats_platform"] == "lever" and slugless["slug"] == "slugless"


def test_per_entry_failure_is_isolated(tmp_path):
    p = make_registry(tmp_path, [
        {"name": "Boom", "ats_platform": "greenhouse", "slug": "boom", "enabled": True},
        {"name": "Fine", "ats_platform": "greenhouse", "slug": "fine", "enabled": True},
    ])
    def make(ats, slug):
        if slug == "boom":
            raise RuntimeError("board 404")
        return FakeATS([job("https://x.com/fine/1")])
    jobs = CompaniesSource(file=p, make=make).fetch()
    assert [j.url for j in jobs] == ["https://x.com/fine/1"]


def test_missing_registry_yields_no_jobs(tmp_path):
    assert CompaniesSource(file=tmp_path / "nope.json").fetch() == []
