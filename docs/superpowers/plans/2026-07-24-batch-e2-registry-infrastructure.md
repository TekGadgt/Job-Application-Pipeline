# Batch E2 — Registry Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The `companies.json` registry drives intake — a `type: companies` meta-source expands enabled entries into per-ATS sources, extract stops clobbering deterministically-sourced fields, manual URLs matching known ATS patterns auto-append registry entries, and registry fit-notes reach the score agent.

**Architecture:** Implements the code portion of `docs/superpowers/specs/2026-07-24-company-registry-discovery-design.md` (wave E2 of Batch E; E1 research seeds the registry independently). Ownership principle is binding: `pipeline.yaml` is human-owned (code never writes it); `companies.json` is machine-owned (comment-free JSON; the only files code writes are it and the vault). ATS URL patterns come from `docs/JobBoardDetection.md`. Mappers beyond existing greenhouse/lever are E3's job — the companies source must degrade gracefully (count + warn) for platforms without mappers.

**Tech Stack:** Python 3.12, pydantic v2, pytest, httpx (existing). No network, no model tokens in tests.

## Global Constraints

- Machine writes go ONLY to `companies.json` (and the vault). Never `pipeline.yaml`.
- `ats_platform: workable` is NEVER fetched (aggressive IP bans per `docs/JobBoardDetection.md`) — refuse with a warning.
- Registry loading is tolerant: bad entries warn + skip; a missing registry file warns + yields `[]`. Never crash the run over data.
- Extract writes ONLY blank fields (`""`/`None`/`[]`) — deterministic prefill is authoritative.
- Per-entry fetch failures stay isolated (one dead board doesn't kill the run) — same policy as `run_pipeline`'s source loop.
- Tests must not use network or real model calls.
- Run tests with `.venv/bin/pytest` from the worktree root (worktree venv; plain `pytest` is not on PATH).
- Commit after every task; `feat:`/`docs:` prefixes, imperative mood.

---

### Task 1: Registry model + loader

**Files:**
- Modify: `job_pipeline/config.py`, `.gitignore`
- Create: `config/companies.example.json`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `CompanyEntry(BaseModel)` (fields below), `load_companies(path: Path | str) -> list[CompanyEntry]`, `save_companies(path, entries)` (atomic full-file rewrite, `indent=2`). Tasks 2 and 4 consume all three.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
COMPANIES = """[
  {"name": "OldCo", "ats_platform": "greenhouse", "slug": "oldco",
   "notes": "marketplace, Vue stack", "source": "claude_research_batch_1"},
  {"name": "Disabled Inc", "ats_platform": "lever", "slug": "disabledinc", "enabled": false},
  {"no_name": "broken entry"}
]"""


def test_load_companies_tolerant(tmp_path, caplog):
    from job_pipeline.config import load_companies
    p = tmp_path / "companies.json"
    p.write_text(COMPANIES)
    entries = load_companies(p)
    assert [e.name for e in entries] == ["OldCo", "Disabled Inc"]   # bad entry skipped
    assert entries[0].enabled is True                                # default
    assert entries[1].enabled is False
    assert "skipping" in caplog.text.lower()


def test_load_companies_missing_file_warns_empty(tmp_path, caplog):
    from job_pipeline.config import load_companies
    assert load_companies(tmp_path / "nope.json") == []
    assert "nope.json" in caplog.text


def test_save_companies_round_trips(tmp_path):
    from job_pipeline.config import CompanyEntry, load_companies, save_companies
    p = tmp_path / "companies.json"
    save_companies(p, [CompanyEntry(name="A", ats_platform="lever", slug="a")])
    entries = load_companies(p)
    assert entries[0].slug == "a"
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: three new tests FAIL (ImportError); rest PASS.

- [ ] **Step 3: Implement in `config.py`**

```python
import json
import logging

log = logging.getLogger("job_pipeline")


class CompanyEntry(BaseModel):
    name: str
    website: str | None = None
    careers_url: str | None = None
    ats_platform: str | None = None
    slug: str | None = None
    domain: str | None = None
    company_size: str | None = None
    stage: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    notes: str | None = None
    source: str | None = None
    enabled: bool = True


def load_companies(path: Path | str) -> list[CompanyEntry]:
    """Tolerant registry load: bad entries warn+skip, missing file warns+[]."""
    path = Path(path).expanduser()
    if not path.exists():
        log.warning("companies registry %s not found; no companies loaded", path)
        return []
    entries: list[CompanyEntry] = []
    for i, raw in enumerate(json.loads(path.read_text())):
        try:
            entries.append(CompanyEntry(**raw))
        except Exception as exc:  # noqa: BLE001 — data file, never crash the run
            log.warning("companies registry: skipping entry %d: %s", i, exc)
    return entries


def save_companies(path: Path | str, entries: list[CompanyEntry]) -> None:
    Path(path).expanduser().write_text(
        json.dumps([e.model_dump(exclude_none=False) for e in entries], indent=2) + "\n"
    )
```

`.gitignore`: add `config/companies.json` and `companies.json` under the personal-data section.

`config/companies.example.json`:

```json
[
  {
    "name": "Example Co",
    "website": "https://example.com",
    "careers_url": "https://boards.greenhouse.io/exampleco",
    "ats_platform": "greenhouse",
    "slug": "exampleco",
    "domain": "developer tools",
    "company_size": "scaleup",
    "stage": "series_b",
    "location": "Remote",
    "remote_policy": "fully_remote",
    "notes": "Why this company fits — the score agent reads this.",
    "source": "claude_research_batch_1",
    "enabled": true
  }
]
```

- [ ] **Step 4: Run the full suite** — `.venv/bin/pytest`, all PASS.
- [ ] **Step 5: Commit** — `git add job_pipeline/config.py tests/test_config.py config/companies.example.json .gitignore && git commit -m "feat: companies.json registry model + tolerant loader"`

---

### Task 2: ATS detection table

**Files:**
- Create: `job_pipeline/ats_patterns.py`
- Test: `tests/test_ats_patterns.py` (new)

**Interfaces:**
- Produces: `detect(url: str) -> tuple[str, str] | None` returning `(ats_platform, slug)`; `PATTERNS` ordered list. Tasks 3 and 5 consume `detect`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_ats_patterns.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure** — `.venv/bin/pytest tests/test_ats_patterns.py -v` → ModuleNotFoundError.

- [ ] **Step 3: Implement `job_pipeline/ats_patterns.py`**

```python
"""ATS detection: URL patterns -> (platform, slug). Source: docs/JobBoardDetection.md."""
from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?P<slug>[^/?#]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/(?P<slug>[^/?#]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/(?P<slug>[^/?#]+)")),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/(?P<slug>[^/?#]+)")),
    ("workday", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com", re.I)),
    ("ultipro", re.compile(r"recruiting\.ultipro\.com/(?P<slug>[^/?#]+)")),
    ("icims", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.icims\.com", re.I)),
    ("taleo", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.taleo\.net", re.I)),
    ("oraclecloud", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.oraclecloud\.com", re.I)),
    ("bamboohr", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.bamboohr\.com", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?P<slug>[^/?#]+)")),
    ("jobvite", re.compile(r"jobs\.jobvite\.com/(?P<slug>[^/?#]+)")),
    ("eightfold", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.eightfold\.ai", re.I)),
    ("teamtailor", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.teamtailor\.com", re.I)),
    ("breezy", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.breezy\.hr", re.I)),
    ("recruitee", re.compile(r"https?://(?P<slug>[a-z0-9-]+)\.recruitee\.com", re.I)),
]


def detect(url: str) -> tuple[str, str] | None:
    """Match a URL against known ATS patterns; return (platform, slug) or None."""
    for platform, pattern in PATTERNS:
        m = pattern.search(url)
        if m:
            return platform, m.group("slug")
    return None
```

- [ ] **Step 4: Run the full suite** — `.venv/bin/pytest`, all PASS.
- [ ] **Step 5: Commit** — `git add job_pipeline/ats_patterns.py tests/test_ats_patterns.py && git commit -m "feat: ATS detection table (url pattern -> platform, slug)"`

---

### Task 3: Companies meta-source

**Files:**
- Create: `job_pipeline/sources/companies.py`
- Modify: `job_pipeline/core/job.py` (one field), `job_pipeline/sources/__init__.py` or the side-effect import block in `core/pipeline.py:17-23` (register the module), `config/pipeline.example.yaml`
- Test: `tests/test_companies_source.py` (new)

**Interfaces:**
- Consumes: `load_companies`/`save_companies`/`CompanyEntry` (Task 1), `detect` (Task 2), `get_source` from `core/registry`.
- Produces: `CompaniesSource(file, make=None)` registered as `"companies"`; `Job.company_context: str = ""` (new field after `extract_hint` in `core/job.py`); jobs fetched via the registry carry `company` (registry name) and `company_context` (registry notes). Task 5 consumes `company_context`. The `make` seam: `make(ats: str, slug: str) -> Source` — default builds from the source registry (`greenhouse` → `get_source("greenhouse")(board=slug)`, `lever` → `get_source("lever")(org=slug)`); tests inject fakes. NOTE for implementer: confirm the greenhouse/lever constructor kwarg names against `job_pipeline/sources/feeds.py` before writing the default map — the example yaml uses `board:` and `org:`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_companies_source.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure** — ModuleNotFoundError.

- [ ] **Step 3: Implement**

`core/job.py`: add after `extract_hint`:

```python
    company_context: str = ""          # registry fit-notes, fed to the score agent
```

`job_pipeline/sources/companies.py`:

```python
"""Meta-source: expand the companies.json registry into per-ATS sources."""
from __future__ import annotations

import logging
from pathlib import Path

from job_pipeline.ats_patterns import detect
from job_pipeline.config import load_companies, save_companies
from job_pipeline.core.job import Job
from job_pipeline.core.registry import get_source, register_source

log = logging.getLogger("job_pipeline")

BANNED = {"workable"}   # aggressive IP bans — see docs/JobBoardDetection.md


def _default_make(ats: str, slug: str):
    if ats == "greenhouse":
        return get_source("greenhouse")(board=slug)
    if ats == "lever":
        return get_source("lever")(org=slug)
    raise KeyError(ats)


SUPPORTED = {"greenhouse", "lever"}   # E3 extends: ashby, smartrecruiters, ...


@register_source("companies")
class CompaniesSource:
    def __init__(self, file: Path | str, make=None) -> None:
        self.file = Path(file).expanduser()
        self.make = make or _default_make

    def fetch(self) -> list[Job]:
        entries = load_companies(self.file)
        jobs: list[Job] = []
        unsupported = 0
        dirty = False
        for entry in entries:
            if not entry.enabled:
                continue
            if entry.slug is None and entry.careers_url:
                hit = detect(entry.careers_url)
                if hit:
                    entry.ats_platform, entry.slug = hit
                    dirty = True
            if entry.ats_platform in BANNED:
                log.warning("refusing %s (%s): banned platform", entry.name, entry.ats_platform)
                continue
            if entry.ats_platform not in SUPPORTED or not entry.slug:
                unsupported += 1
                continue
            try:
                fetched = self.make(entry.ats_platform, entry.slug).fetch()
            except Exception as exc:  # noqa: BLE001 — one dead board doesn't kill the run
                log.warning("companies: %s (%s/%s) failed: %s",
                            entry.name, entry.ats_platform, entry.slug, exc)
                continue
            for j in fetched:
                j.company = entry.name
                j.company_context = entry.notes or ""
            jobs.extend(fetched)
        if dirty:
            save_companies(self.file, entries)
        if unsupported:
            log.info("companies: %d entries await unsupported-platform mappers (E3/E4)", unsupported)
        return jobs

    def on_terminal(self, job: Job) -> None:
        pass
```

Register the module for side-effect import wherever the other sources are imported (`core/pipeline.py:17-23`): `import job_pipeline.sources.companies  # noqa: F401`.

`config/pipeline.example.yaml` sources block gains a commented line:
```yaml
  # - {type: companies, file: companies.json}   # machine-owned registry (see README)
```

- [ ] **Step 4: Run the full suite** — `.venv/bin/pytest`, all PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: companies meta-source — registry expansion, slug resolution, banned/unsupported policy"`

---

### Task 4: Gap-filling extract

**Files:**
- Modify: `job_pipeline/stages/agents/extract.py`
- Test: `tests/test_agent_stages.py`

**Interfaces:**
- Consumes: nothing new. Produces: extract writes only blank fields (`""`/`None`/`[]`); skips the runner entirely when no extract-owned field is blank; `EXTRACT_PROMPT` gains a `{known_fields}` slot (frozen constant preserved — the slot is filled per job like `{source_context}`).

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_agent_stages.py` (reuse its existing fixtures/reply dict — read the file first; the reply constant at the top maps extract fields):

```python
def test_extract_gap_fills_not_clobbers(profile_and_runner_fixtures_as_appropriate):
    # Build a job with prefilled title/location (as a structured source would),
    # run ExtractStage with a MockRunner reply that CONTRADICTS them,
    # assert job.title/location keep the prefilled values while blank fields
    # (description, requirements, comp_*) take the reply's values.
    ...


def test_extract_skips_runner_when_nothing_blank(...):
    # Prefill every ExtractReply field on the job (incl. description/requirements),
    # run ExtractStage with MockRunner([]) — no replies available.
    # Assert: no exception, trace contains "skipped", fields unchanged.
    ...
```

Write these as real tests against the file's actual fixture style — the two `...` bodies above describe intent, the implementer writes them concretely following the existing tests in that file (e.g. `test_extract_parses_reply`). The assertions that matter: prefilled values survive a contradicting reply; blank fields are filled; fully-prefilled job makes zero runner calls and traces `skipped`.

- [ ] **Step 2: Run to verify failures** — `.venv/bin/pytest tests/test_agent_stages.py -v`.

- [ ] **Step 3: Implement in `extract.py`**

Replace the prompt constant's first line and the `run` body:

```python
EXTRACT_PROMPT = """{source_context}{known_fields}Extract structured fields from this job listing. Reply with ONLY a JSON object:
{"title": str, "company": str, "location": str, "comp_text": str,
 "comp_min": int|null, "comp_max": int|null, "comp_currency": str|null,
 "comp_period": "annual"|"hourly"|null, "requirements": [str], "description": str,
 "employer_address": str, "employer_phone": str, "employer_email": str}
comp_min/comp_max are numbers only (e.g. "$150k" -> 150000). Use "" / null / [] when absent.
description is a 2-3 sentence summary.

LISTING:
{raw_text}"""


def _is_blank(value) -> bool:
    return value in ("", None) or value == []


class ExtractStage:
    ...
    def run(self, job: Job) -> Job:
        blanks = [f for f in ExtractReply.model_fields if _is_blank(getattr(job, f))]
        if not blanks:
            job.add_trace("extract", "skipped: all fields prefilled")
            return job
        known = {f: getattr(job, f) for f in ExtractReply.model_fields
                 if not _is_blank(getattr(job, f))}
        known_fields = (
            f"ALREADY KNOWN (authoritative, do not contradict): {known}\n\n" if known else ""
        )
        source_context = (
            f"SOURCE CONTEXT: {job.extract_hint}\n\n" if job.extract_hint else ""
        )
        reply = self.runner.run(
            _fill(EXTRACT_PROMPT, source_context=source_context,
                  known_fields=known_fields, raw_text=job.raw_text),
            self.model, ExtractReply,
        )
        for field_name, value in reply.model_dump().items():
            if field_name in blanks:
                setattr(job, field_name, value)
        job.add_trace("extract", f"extracted ({len(blanks)} fields; {len(known)} prefilled)")
        return job
```

- [ ] **Step 4: Run the full suite** — `.venv/bin/pytest`, all PASS (existing extract tests have fully-blank jobs, so behavior there is unchanged).
- [ ] **Step 5: Commit** — `git add job_pipeline/stages/agents/extract.py tests/test_agent_stages.py && git commit -m "feat: extract gap-fills — prefilled fields are authoritative"`

---

### Task 5: URL harvesting + score context + docs

**Files:**
- Modify: `job_pipeline/sources/companies.py` (harvest helper), `job_pipeline/core/pipeline.py`, `job_pipeline/stages/agents/score.py`, `README.md`
- Test: `tests/test_companies_source.py`, `tests/test_agent_stages.py`, `tests/test_pipeline_e2e.py`

**Interfaces:**
- Consumes: `detect` (Task 2), registry IO (Task 1), `Job.company_context` (Task 3).
- Produces: `harvest_urls(registry_path: Path, urls: list[str]) -> int` in `sources/companies.py` (appends new entries, returns count added); `run_pipeline` calls it for manual-source jobs when a `{type: companies, file:}` entry exists in `cfg.sources`; `SCORE_PROMPT` gains a `{company_context}` slot.

- [ ] **Step 1: Write the failing tests**

`tests/test_companies_source.py`:

```python
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
```

`tests/test_agent_stages.py` — score context test (follow the file's existing score-test style): run `ScoreStage` on a job with `company_context="great fit"` using a recording fake runner (or MockRunner + captured prompt if the file already captures prompts); assert the prompt contains `COMPANY CONTEXT: great fit`; run again with empty `company_context` and assert the marker is absent.

`tests/test_pipeline_e2e.py` — harvesting wiring test: config whose `sources` includes `{"type": "companies", "file": str(registry_path)}`, run with a manual-source job whose URL is a greenhouse URL (FakeSource with `source="manual"` jobs is fine — `run_pipeline` keys off `job.source == "manual"`); assert the registry file gained the harvested entry. Keep the stage list `[dedup]` so no agent replies are needed.

- [ ] **Step 2: Run to verify failures.**

- [ ] **Step 3: Implement**

`sources/companies.py`:

```python
def harvest_urls(registry_path: Path | str, urls: list[str]) -> int:
    """Append registry entries for manual URLs matching known ATS patterns."""
    entries = load_companies(registry_path)
    known = {(e.ats_platform, e.slug) for e in entries}
    added = 0
    for url in urls:
        hit = detect(url)
        if not hit or hit in known:
            continue
        ats, slug = hit
        entries.append(CompanyEntry(name=slug, ats_platform=ats, slug=slug,
                                    source="url_harvest", enabled=True))
        known.add(hit)
        added += 1
        log.info("harvested %s as %s source (from %s)", slug, ats, url)
    if added:
        save_companies(registry_path, entries)
    return added
```

(import `CompanyEntry` alongside the existing config imports.)

`core/pipeline.py`, in `run_pipeline` after the jobs-collection loop and before `build_stages`:

```python
    registry_file = next(
        (s.get("file") for s in cfg.sources if s.get("type") == "companies"), None)
    if registry_file:
        manual_urls = [j.url for j in jobs if j.source == "manual"]
        if manual_urls:
            from job_pipeline.sources.companies import harvest_urls
            harvest_urls(registry_file, manual_urls)
```

`score.py` — add the slot to the frozen constant and fill it:

```python
SCORE_PROMPT = """Score this job 0-100 for fit against the candidate's profile and preferences.
Reply with ONLY a JSON object: {"score": number, "rationale": str}
The rationale should be 2-4 sentences naming the decisive factors.

CANDIDATE PROFILE AND PREFERENCES:
{profile_body}

{company_context}JOB: {title} at {company} ({location}) — {comp_text}
DESCRIPTION: {description}
SKILL GAP: {skill_gap}"""
```

and in `run()`:

```python
        company_context = (
            f"COMPANY CONTEXT: {job.company_context}\n\n" if job.company_context else ""
        )
```

passed through `_fill(..., company_context=company_context, ...)`.

`README.md` (read it first): a "Company registry" subsection near the sources docs — ownership split (yaml human-owned / companies.json machine-owned + gitignored, example file), the `{type: companies}` source line, URL harvesting behavior (manual URLs matching `docs/JobBoardDetection.md` patterns auto-append, fetched next run), wave activation via `enabled`, the Workable refusal, and the E3 note that unsupported platforms are counted and skipped until their mappers land.

- [ ] **Step 4: Run the full suite** — `.venv/bin/pytest`, all PASS.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: url harvesting into registry + score-agent company context + docs"`

---

## Post-plan notes for the executor

- Branch: `feat/batch-e2-registry` off current main; Ryan pushes/PRs/merges himself — do not push.
- Worktree venv: `python -m venv .venv` from the main checkout's `.venv/bin/python`, then `.venv/bin/pip install -e ".[dev]"`.
- The live vault and Ryan's real `config/companies.json` (may exist after E1 research lands) are user data — never run the CLI against live config during development.
- Task 4's Step 1 intentionally describes test intent rather than verbatim code: `tests/test_agent_stages.py` has existing fixtures the tests must reuse; read the file and match its style. Everything else in this plan is exact.
