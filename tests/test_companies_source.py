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


def test_harvest_appends_new_entry_once(tmp_path):
    from job_pipeline.sources.companies import harvest_urls
    p = make_registry(tmp_path, [])
    added = harvest_urls(p, [
        "https://boards.greenhouse.io/newco/jobs/1",
        "https://boards.greenhouse.io/newco/jobs/2",     # same slug: once
        "https://example.com/careers",                    # no match: ignored
    ])
    assert added == 1
    saved = json.loads(p.read_text())
    assert len(saved) == 1
    e = saved[0]
    assert e["name"] == "newco" and e["ats_platform"] == "greenhouse"
    assert e["slug"] == "newco" and e["source"] == "url_harvest" and e["enabled"] is True


def test_harvest_ignores_known_slug(tmp_path):
    from job_pipeline.sources.companies import harvest_urls
    p = make_registry(tmp_path)          # REGISTRY already has greenhouse/goodco
    assert harvest_urls(p, ["https://boards.greenhouse.io/goodco/jobs/9"]) == 0
    assert len(json.loads(p.read_text())) == len(REGISTRY)


def test_duplicate_platform_slug_entries_fetched_once(tmp_path):
    # FINDING 3: two registry entries resolving to the same (ats, slug) must
    # only be fetched once per run.
    p = make_registry(tmp_path, [
        {"name": "Dup A", "ats_platform": "greenhouse", "slug": "sameco", "enabled": True},
        {"name": "Dup B", "ats_platform": "greenhouse", "slug": "sameco", "enabled": True},
    ])
    calls = []
    def make(ats, slug):
        calls.append((ats, slug))
        return FakeATS([job(f"https://x.com/{slug}/1")])
    jobs = CompaniesSource(file=p, make=make).fetch()
    assert calls == [("greenhouse", "sameco")]
    assert len(jobs) == 1


def test_harvest_urls_skips_banned_platform(tmp_path):
    # FINDING 6a: banned-platform URLs must never be written into the registry.
    from job_pipeline.sources.companies import harvest_urls
    p = make_registry(tmp_path, [])
    added = harvest_urls(p, ["https://apply.workable.com/bannedco/"])
    assert added == 0
    assert json.loads(p.read_text()) == []


def test_banned_platform_resolution_does_not_persist(tmp_path):
    # FINDING 6b: when careers_url resolution lands on a banned platform, the
    # registry file must not be rewritten (dirty flag must not be set).
    p = make_registry(tmp_path, [
        {"name": "Slugless Banned", "ats_platform": None, "slug": None,
         "careers_url": "https://apply.workable.com/bannedco/", "enabled": True},
    ])
    before = p.read_text()
    jobs = CompaniesSource(file=p, make=lambda ats, slug: FakeATS([])).fetch()
    assert jobs == []
    assert p.read_text() == before   # untouched: no rewrite


def test_banned_platform_resolution_does_not_persist_when_other_entry_is_dirty(tmp_path):
    # FINDING 6b (multi-entry): the prior fix suppressed `dirty` for the banned
    # entry but still mutated it in memory. If ANY other entry in the same run
    # sets dirty (e.g. a legitimate slugless -> greenhouse resolution), the
    # whole entries list is written out, including the banned entry's
    # in-memory-mutated ats_platform/slug. The banned entry must never be
    # persisted with a resolved platform/slug, regardless of what else in the
    # registry triggers a save this run.
    p = make_registry(tmp_path, [
        {"name": "Slugless Banned", "ats_platform": None, "slug": None,
         "careers_url": "https://apply.workable.com/bannedco/", "enabled": True},
        {"name": "Slugless Good", "ats_platform": None, "slug": None,
         "careers_url": "https://boards.greenhouse.io/goodco/jobs/1", "enabled": True},
    ])
    jobs = CompaniesSource(file=p, make=lambda ats, slug: FakeATS([])).fetch()
    assert jobs == []
    saved = json.loads(p.read_text())
    banned = next(e for e in saved if e["name"] == "Slugless Banned")
    assert banned["ats_platform"] is None
    assert banned["slug"] is None
    good = next(e for e in saved if e["name"] == "Slugless Good")
    assert good["ats_platform"] == "greenhouse" and good["slug"] == "goodco"


def test_supported_platform_missing_slug_warns_distinctly(tmp_path, caplog):
    import logging
    caplog.set_level(logging.WARNING, logger="job_pipeline")
    p = make_registry(tmp_path, [
        {"name": "Slugless Greenhouse Co", "ats_platform": "greenhouse",
         "slug": None, "enabled": True},
    ])
    assert CompaniesSource(file=p, make=lambda a, s: FakeATS([])).fetch() == []
    assert "has no slug" in caplog.text
    assert "Slugless Greenhouse Co" in caplog.text
    # must NOT be reported as an unsupported-platform entry
    assert "await unsupported-platform mappers" not in caplog.text
