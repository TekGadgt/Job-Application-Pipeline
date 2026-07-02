# Job Application Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A config-driven job pipeline: intake (feeds + manual URLs) → deterministic filters → three Agent-SDK stages (extract, skill-gap, score) → Obsidian notes that double as VEC work-search records.

**Architecture:** "Fat code, thin agents." A deterministic orchestrator walks a config-defined stage list; each stage implements `run(job) -> job` and exposes a `StageSpec`. Rule stages are pure Python; agent stages call a swappable `AgentRunner`. Sources yield jobs, Seeders pre-populate the dedup index. Personal data (profile, pipeline config, seen-index, vault) is gitignored; the repo ships `*.example` templates.

**Tech Stack:** Python 3.11+, pydantic v2, PyYAML, feedparser, httpx, pytest, `claude-agent-sdk` (subscription-auth agent runner). SQLite via stdlib `sqlite3`.

**Spec:** `docs/superpowers/specs/2026-07-02-job-application-pipeline-design.md`

## Global Constraints

- **Subscription-only billing:** agent calls go through the **Claude Agent SDK** (`claude-agent-sdk` package), never the raw `anthropic` API client. The SDK rides the user's logged-in Claude Code credentials. The SDK runner must refuse to run if `ANTHROPIC_API_KEY` is set (that env var silently flips billing to pay-as-you-go API credits).
- **No automated applying.** The pipeline discovers/scores/publishes only. `date_of_contact`, `employer_contact_person`, `result_of_contact` are filled by the user when they act.
- **Default test suite uses no network and no tokens.** All agent stages tested via `MockRunner`. Real SDK calls only in a test marked `@pytest.mark.integration`, excluded by default.
- **No personal data in the repo.** `config/profile.md`, `config/pipeline.yaml`, `*.sqlite` are gitignored (already configured). Only `config/*.example.*` are committed.
- **Package name:** `job_pipeline`. **Python:** ≥3.11 (uses `X | None` syntax and `datetime.UTC`).
- **Stage interface:** `run(job: Job) -> Job`; stages are pure (no I/O except publish/dedup via injected stores) and idempotent.
- **Model tiers in config:** `models: {extract: haiku, skill_gap: sonnet, score: opus}` — passed to the runner verbatim (Claude Code accepts `haiku`/`sonnet`/`opus` aliases).
- Run all commands from the repo root: `/Users/tekgadgt/projects/job_application_pipeline`. Use `python3 -m pytest`.
- Commit after every task with the message shown in the task.

---

### Task 1: Project scaffolding + `Job` dataclass

**Files:**
- Create: `pyproject.toml`
- Create: `job_pipeline/__init__.py`, `job_pipeline/core/__init__.py`
- Create: `job_pipeline/core/job.py`
- Create: `tests/__init__.py`
- Test: `tests/test_job.py`

**Interfaces:**
- Produces: `Job` dataclass (fields below — all later tasks depend on these exact names); `Job.mark_rejected(stage, reason)`, `Job.mark_errored(stage, error)`, `Job.add_trace(stage, verdict)`.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "job-pipeline"
version = "0.1.0"
description = "Config-driven job discovery/scoring pipeline publishing to Obsidian"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.0",
    "pyyaml>=6.0",
    "feedparser>=6.0",
    "httpx>=0.27",
    "claude-agent-sdk>=0.1.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[project.scripts]
job-pipeline = "job_pipeline.cli:main"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["job_pipeline*"]

[tool.pytest.ini_options]
markers = ["integration: hits the real Agent SDK (excluded by default)"]
addopts = "-m 'not integration'"
```

- [ ] **Step 2: Install in editable mode**

Run: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'`
Expected: installs cleanly. (Use `.venv/bin/python -m pytest` for all test commands below; abbreviated to `pytest` from here.)

- [ ] **Step 3: Write the failing test**

```python
# tests/test_job.py
from datetime import datetime, UTC
from job_pipeline.core.job import Job


def make_job(url="https://example.com/j/1"):
    return Job(source="test", url=url, raw_text="text", fetched_at=datetime.now(UTC))


def test_id_is_stable_hash_of_url():
    a, b = make_job(), make_job()
    assert a.id == b.id and len(a.id) == 16
    assert make_job("https://example.com/j/2").id != a.id


def test_mark_rejected_sets_verdict_and_trace():
    j = make_job()
    j.mark_rejected("hard_filter", "blocklist: web3")
    assert j.rejected and j.reject_stage == "hard_filter"
    assert j.reject_reason == "blocklist: web3"
    assert j.trace[-1][0] == "hard_filter" and j.trace[-1][1] == "rejected: blocklist: web3"


def test_mark_errored_is_distinct_from_rejected():
    j = make_job()
    j.mark_errored("extract", "boom")
    assert j.errored and not j.rejected and j.error == "boom"


def test_defaults():
    j = make_job()
    assert j.comp_min is None and j.salary_ok is None
    assert j.requirements == [] and j.skill_gap == {} and j.trace == []
```

- [ ] **Step 4: Run test to verify it fails**

Run: `pytest tests/test_job.py -v`
Expected: FAIL — `ModuleNotFoundError: job_pipeline.core.job`

- [ ] **Step 5: Write the implementation**

```python
# job_pipeline/core/job.py
"""The Job record that flows through every pipeline stage."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, UTC


@dataclass
class Job:
    # intake
    source: str
    url: str
    raw_text: str
    fetched_at: datetime
    id: str = ""                       # stable hash(url) — primary dedup key
    # after extract (agent)
    title: str = ""
    company: str = ""
    location: str = ""
    comp_text: str = ""                # verbatim comp string, for display
    comp_min: int | None = None        # numeric, parsed by the extract agent
    comp_max: int | None = None
    comp_currency: str | None = None   # e.g. "USD"
    comp_period: str | None = None     # "annual" | "hourly"
    fuzzy_key: str = ""                # normalize(company)+normalize(title)
    requirements: list[str] = field(default_factory=list)
    description: str = ""
    employer_address: str = ""         # VEC, if present in listing
    employer_phone: str = ""
    employer_email: str = ""
    # after rule stages
    location_ok: bool | None = None
    salary_ok: bool | None = None
    # after agent stages
    skill_gap: dict = field(default_factory=dict)   # {have, missing, partial}
    score: float | None = None
    score_rationale: str = ""
    # bookkeeping
    trace: list[tuple[str, str, str]] = field(default_factory=list)
    rejected: bool = False
    reject_reason: str | None = None
    reject_stage: str | None = None
    errored: bool = False
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = hashlib.sha256(self.url.encode()).hexdigest()[:16]

    def add_trace(self, stage: str, verdict: str) -> None:
        self.trace.append((stage, verdict, datetime.now(UTC).isoformat()))

    def mark_rejected(self, stage: str, reason: str) -> None:
        self.rejected = True
        self.reject_stage = stage
        self.reject_reason = reason
        self.add_trace(stage, f"rejected: {reason}")

    def mark_errored(self, stage: str, error: str) -> None:
        self.errored = True
        self.error = error
        self.add_trace(stage, f"errored: {error}")
```

Also create empty `job_pipeline/__init__.py`, `job_pipeline/core/__init__.py`, `tests/__init__.py`.

- [ ] **Step 6: Run test to verify it passes**

Run: `pytest tests/test_job.py -v` — Expected: 4 PASS

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml job_pipeline tests
git commit -m "feat: scaffold package and Job dataclass"
```

---

### Task 2: Stage protocol, StageSpec, and registries

**Files:**
- Create: `job_pipeline/core/stage.py`, `job_pipeline/core/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Job` (Task 1)
- Produces: `StageSpec(name, purpose, requires, produces, kind, cost_tier)`; `Stage` protocol with `.spec: StageSpec` and `.run(job) -> Job`; registries `register_stage(name)`, `get_stage(name)`, `register_source(name)`, `get_source(name)`, `register_seeder(name)`, `get_seeder(name)` — all decorator-based, raising `KeyError` with known names listed on miss.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_registry.py
import pytest
from job_pipeline.core.registry import (
    register_stage, get_stage, register_source, get_source,
    register_seeder, get_seeder,
)
from job_pipeline.core.stage import StageSpec


def test_register_and_get_stage():
    @register_stage("demo")
    class Demo:
        spec = StageSpec(name="demo", purpose="test", requires=[], produces=[],
                         kind="deterministic", cost_tier="free")
        def run(self, job):
            return job
    assert get_stage("demo") is Demo


def test_unknown_name_raises_keyerror_listing_known():
    with pytest.raises(KeyError, match="demo"):
        get_stage("nope")


def test_source_and_seeder_registries_are_separate():
    @register_source("src")
    class Src: ...
    @register_seeder("seed")
    class Seed: ...
    assert get_source("src") is Src and get_seeder("seed") is Seed
    with pytest.raises(KeyError):
        get_source("seed")
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_registry.py -v` → ModuleNotFoundError

- [ ] **Step 3: Implement**

```python
# job_pipeline/core/stage.py
"""Stage protocol and the self-describing StageSpec descriptor."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from job_pipeline.core.job import Job


@dataclass(frozen=True)
class StageSpec:
    name: str
    purpose: str                    # human/LLM-readable
    requires: list[str]             # Job fields this stage reads
    produces: list[str]             # Job fields this stage sets
    kind: Literal["deterministic", "agent"]
    cost_tier: Literal["free", "cheap", "mid", "expensive"]


@runtime_checkable
class Stage(Protocol):
    spec: StageSpec

    def run(self, job: Job) -> Job: ...
```

```python
# job_pipeline/core/registry.py
"""Name -> class registries: the extensibility seam for stages/sources/seeders."""
from __future__ import annotations

_STAGES: dict[str, type] = {}
_SOURCES: dict[str, type] = {}
_SEEDERS: dict[str, type] = {}


def _make_pair(table: dict[str, type], kind: str):
    def register(name: str):
        def deco(cls: type) -> type:
            table[name] = cls
            return cls
        return deco

    def get(name: str) -> type:
        try:
            return table[name]
        except KeyError:
            raise KeyError(
                f"unknown {kind} {name!r}; known: {sorted(table)}"
            ) from None
    return register, get


register_stage, get_stage = _make_pair(_STAGES, "stage")
register_source, get_source = _make_pair(_SOURCES, "source")
register_seeder, get_seeder = _make_pair(_SEEDERS, "seeder")
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_registry.py -v`

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: Stage protocol, StageSpec, and name registries"`

---

### Task 3: Config loading (profile.md + pipeline.yaml) with fail-fast validation

**Files:**
- Create: `job_pipeline/config.py`
- Create: `config/profile.example.md`, `config/pipeline.example.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Profile` pydantic model (`salary_floor: int|None`, `locations: LocationRules(remote: bool, allowed_metros: list[str])`, `blocklist: list[str]`, `must_have_skills: list[str]`, `nice_to_have: list[str]`, `salary_not_listed: Literal["keep","reject"]`, `body: str`); `PipelineConfig` (`sources: list[dict]`, `seeders: list[dict]`, `stages: list[str]`, `models: dict[str,str]`, `output: OutputConfig(vault: Path, keep_rejects: bool)`, `limits: Limits(max_agent_jobs_per_run: int)`); loaders `load_profile(path) -> Profile`, `load_pipeline_config(path) -> PipelineConfig`. Invalid input raises `pydantic.ValidationError` or `ValueError` before any other work.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import pytest
from pydantic import ValidationError
from job_pipeline.config import load_profile, load_pipeline_config

PROFILE = """---
salary_floor: 140000
locations: {remote: true, allowed_metros: ["Richmond, VA"]}
blocklist: [crypto, web3]
must_have_skills: [python]
nice_to_have: [rust]
salary_not_listed: keep
---
## Base resume
I write Python.
"""

PIPELINE = """
sources:
  - {type: rss, url: "https://example.com/feed"}
seeders: []
stages: [dedup, hard_filter]
models: {extract: haiku, skill_gap: sonnet, score: opus}
output: {vault: /tmp/vault, keep_rejects: true}
limits: {max_agent_jobs_per_run: 40}
"""


def test_load_profile_parses_frontmatter_and_body(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text(PROFILE)
    prof = load_profile(p)
    assert prof.salary_floor == 140000
    assert prof.locations.remote is True
    assert "web3" in prof.blocklist
    assert "I write Python." in prof.body


def test_profile_rejects_bad_salary_not_listed(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text(PROFILE.replace("salary_not_listed: keep", "salary_not_listed: maybe"))
    with pytest.raises(ValidationError):
        load_profile(p)


def test_profile_requires_frontmatter(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text("no frontmatter here")
    with pytest.raises(ValueError, match="frontmatter"):
        load_profile(p)


def test_load_pipeline_config(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE)
    cfg = load_pipeline_config(p)
    assert cfg.stages == ["dedup", "hard_filter"]
    assert cfg.models["score"] == "opus"
    assert cfg.limits.max_agent_jobs_per_run == 40


def test_pipeline_config_rejects_negative_cap(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE.replace("40", "-1"))
    with pytest.raises(ValidationError):
        load_pipeline_config(p)
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_config.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/config.py
"""Fail-fast config loading: profile.md (YAML frontmatter + prose) and pipeline.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class LocationRules(BaseModel):
    remote: bool = False
    allowed_metros: list[str] = []


class Profile(BaseModel):
    salary_floor: int | None = None
    locations: LocationRules = LocationRules()
    blocklist: list[str] = []
    must_have_skills: list[str] = []
    nice_to_have: list[str] = []
    salary_not_listed: Literal["keep", "reject"] = "keep"
    body: str = ""                      # prose: resume + fuzzy preferences


class OutputConfig(BaseModel):
    vault: Path
    keep_rejects: bool = True


class Limits(BaseModel):
    max_agent_jobs_per_run: int = Field(default=40, gt=0)


class PipelineConfig(BaseModel):
    sources: list[dict] = []
    seeders: list[dict] = []
    stages: list[str]
    models: dict[str, str] = {}
    output: OutputConfig
    limits: Limits = Limits()


def load_profile(path: Path | str) -> Profile:
    text = Path(path).read_text()
    if not text.startswith("---"):
        raise ValueError(f"{path}: profile must start with YAML frontmatter (---)")
    _, fm, body = text.split("---", 2)
    data = yaml.safe_load(fm) or {}
    return Profile(**data, body=body.strip())


def load_pipeline_config(path: Path | str) -> PipelineConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return PipelineConfig(**data)
```

- [ ] **Step 4: Write the committed example configs**

```markdown
<!-- config/profile.example.md -->
---
salary_floor: 100000
locations:
  remote: true
  allowed_metros: ["Richmond, VA"]
blocklist: [crypto, web3, blockchain, defi]
must_have_skills: [python]
nice_to_have: [rust, kubernetes]
salary_not_listed: keep
---
## Base resume

(Paste your resume here. The skill-gap and score agents read this section.)

## What I'm looking for

(Describe the fuzzy stuff: team size, culture, growth, domains you like/avoid.
The score agent weighs this.)
```

```yaml
# config/pipeline.example.yaml
sources:
  - {type: greenhouse, board: examplecompany}
  - {type: lever, org: examplecompany}
  - {type: rss, url: "https://example.com/jobs.rss"}
  - {type: manual, inbox: ~/vault/jobs/inbox.txt}   # one URL per line; consumed on run
seeders:
  - {type: existing_vault, path: ~/vault/jobs, url_field: source_url}
stages: [dedup, hard_filter, extract, dedup_fuzzy, location, salary, skill_gap, score, publish]
models: {extract: haiku, skill_gap: sonnet, score: opus}
output: {vault: ~/vault/jobs, keep_rejects: true}
limits: {max_agent_jobs_per_run: 40}   # overflow: FIFO; deferred jobs retry next run
```

- [ ] **Step 5: Run to verify PASS** — `pytest tests/test_config.py -v`

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: profile/pipeline config loading with fail-fast validation"`

---

### Task 4: Seen-index store (SQLite)

**Files:**
- Create: `job_pipeline/store/__init__.py`, `job_pipeline/store/seen_index.py`
- Test: `tests/test_seen_index.py`

**Interfaces:**
- Produces: `SeenIndex(db_path)` with `has_url(url_hash) -> bool`, `has_fuzzy(fuzzy_key) -> bool`, `mark(url_hash, fuzzy_key="")`, `count() -> int`. Context-manager optional; connection opened lazily; `db_path` parent dirs auto-created.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seen_index.py
from job_pipeline.store.seen_index import SeenIndex


def test_mark_and_lookup(tmp_path):
    idx = SeenIndex(tmp_path / "seen.sqlite")
    assert not idx.has_url("abc")
    idx.mark("abc", "acme|engineer")
    assert idx.has_url("abc")
    assert idx.has_fuzzy("acme|engineer")
    assert not idx.has_fuzzy("other|role")


def test_persists_across_instances(tmp_path):
    db = tmp_path / "seen.sqlite"
    SeenIndex(db).mark("xyz")
    assert SeenIndex(db).has_url("xyz")


def test_mark_is_idempotent(tmp_path):
    idx = SeenIndex(tmp_path / "seen.sqlite")
    idx.mark("abc")
    idx.mark("abc")
    assert idx.count() == 1


def test_empty_fuzzy_key_never_matches(tmp_path):
    idx = SeenIndex(tmp_path / "seen.sqlite")
    idx.mark("abc", "")
    assert not idx.has_fuzzy("")
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_seen_index.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/store/seen_index.py
"""SQLite-backed dedup index. A job is marked seen only on terminal reject or publish."""
from __future__ import annotations

import sqlite3
from pathlib import Path


class SeenIndex:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS seen ("
            " url_hash TEXT PRIMARY KEY,"
            " fuzzy_key TEXT NOT NULL DEFAULT '',"
            " added_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        self._conn.commit()

    def has_url(self, url_hash: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM seen WHERE url_hash = ?", (url_hash,)
        ).fetchone()
        return row is not None

    def has_fuzzy(self, fuzzy_key: str) -> bool:
        if not fuzzy_key:
            return False
        row = self._conn.execute(
            "SELECT 1 FROM seen WHERE fuzzy_key = ?", (fuzzy_key,)
        ).fetchone()
        return row is not None

    def mark(self, url_hash: str, fuzzy_key: str = "") -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO seen (url_hash, fuzzy_key) VALUES (?, ?)",
            (url_hash, fuzzy_key),
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_seen_index.py -v`

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: SQLite seen-index for dedup"`

---

### Task 5: Rule stages — dedup, hard_filter, dedup_fuzzy, location, salary

One task: these are five small pure classes sharing fixtures; a reviewer evaluates them as one unit of "the free filters".

**Files:**
- Create: `job_pipeline/stages/__init__.py`, `job_pipeline/stages/rules.py`
- Test: `tests/test_rule_stages.py`

**Interfaces:**
- Consumes: `Job`, `StageSpec`, registries, `SeenIndex`, `Profile`.
- Produces: registered stages `dedup` (DedupStage(seen_index)), `hard_filter` (HardFilterStage(profile)), `dedup_fuzzy` (FuzzyDedupStage(seen_index)), `location` (LocationStage(profile)), `salary` (SalaryStage(profile)). Also module function `make_fuzzy_key(company, title) -> str` (lowercase, alnum-only, `"{company}|{title}"`). Salary normalizes hourly → annual as `hourly * 2080`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rule_stages.py
from datetime import datetime, UTC
from job_pipeline.core.job import Job
from job_pipeline.config import Profile, LocationRules
from job_pipeline.store.seen_index import SeenIndex
from job_pipeline.stages.rules import (
    DedupStage, HardFilterStage, FuzzyDedupStage, LocationStage, SalaryStage,
    make_fuzzy_key,
)


def make_job(**kw):
    base = dict(source="t", url="https://x.com/1", raw_text="", fetched_at=datetime.now(UTC))
    base.update(kw)
    return Job(**base)


def profile(**kw):
    return Profile(**kw)


# --- dedup ---
def test_dedup_rejects_seen_url(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    j = make_job()
    idx.mark(j.id)
    out = DedupStage(idx).run(make_job())
    assert out.rejected and out.reject_stage == "dedup"


def test_dedup_passes_unseen(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    assert not DedupStage(idx).run(make_job()).rejected


# --- hard filter ---
def test_hard_filter_matches_word_boundary_case_insensitive():
    p = profile(blocklist=["web3", "crypto"])
    st = HardFilterStage(p)
    assert st.run(make_job(raw_text="Exciting Web3 startup!")).rejected
    assert not st.run(make_job(raw_text="cryptography experience a plus")).rejected


def test_hard_filter_records_which_keyword():
    p = profile(blocklist=["defi"])
    out = HardFilterStage(p).run(make_job(raw_text="DeFi protocols"))
    assert "defi" in out.reject_reason


# --- fuzzy key + fuzzy dedup ---
def test_make_fuzzy_key_normalizes():
    assert make_fuzzy_key("Acme, Inc.", "Sr. Engineer") == "acmeinc|srengineer"


def test_fuzzy_dedup_rejects_cross_source_duplicate(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("otherhash", "acme|engineer")
    j = make_job(company="Acme", title="Engineer")
    out = FuzzyDedupStage(idx).run(j)
    assert out.rejected and out.reject_stage == "dedup_fuzzy"
    assert j.fuzzy_key == "acme|engineer"


# --- location ---
def test_location_remote_ok_when_profile_allows_remote():
    p = profile(locations=LocationRules(remote=True, allowed_metros=[]))
    out = LocationStage(p).run(make_job(location="Remote (US)"))
    assert out.location_ok and not out.rejected


def test_location_rejects_disallowed_metro():
    p = profile(locations=LocationRules(remote=False, allowed_metros=["Richmond, VA"]))
    out = LocationStage(p).run(make_job(location="San Francisco, CA"))
    assert out.rejected and out.location_ok is False


def test_location_allows_listed_metro():
    p = profile(locations=LocationRules(remote=False, allowed_metros=["Richmond, VA"]))
    assert not LocationStage(p).run(make_job(location="Richmond, VA (hybrid)")).rejected


# --- salary ---
def test_salary_rejects_below_floor():
    p = profile(salary_floor=140000)
    out = SalaryStage(p).run(make_job(comp_max=120000, comp_period="annual"))
    assert out.rejected and out.salary_ok is False


def test_salary_passes_at_or_above_floor():
    p = profile(salary_floor=140000)
    assert not SalaryStage(p).run(make_job(comp_max=150000, comp_period="annual")).rejected


def test_salary_normalizes_hourly():
    p = profile(salary_floor=140000)
    # $80/hr * 2080 = 166,400 -> pass
    assert not SalaryStage(p).run(make_job(comp_max=80, comp_period="hourly")).rejected


def test_salary_not_listed_keep_vs_reject():
    keep = SalaryStage(profile(salary_floor=140000, salary_not_listed="keep"))
    rej = SalaryStage(profile(salary_floor=140000, salary_not_listed="reject"))
    assert not keep.run(make_job()).rejected
    assert rej.run(make_job()).rejected


def test_salary_no_floor_always_passes():
    assert not SalaryStage(profile()).run(make_job()).rejected
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_rule_stages.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/stages/rules.py
"""The free deterministic filter stages. No model tokens are spent here."""
from __future__ import annotations

import re

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.store.seen_index import SeenIndex

HOURS_PER_YEAR = 2080


def make_fuzzy_key(company: str, title: str) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return f"{norm(company)}|{norm(title)}"


@register_stage("dedup")
class DedupStage:
    spec = StageSpec("dedup", "drop jobs whose URL was already seen",
                     requires=["id"], produces=["rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, seen_index: SeenIndex) -> None:
        self.seen = seen_index

    def run(self, job: Job) -> Job:
        if self.seen.has_url(job.id):
            job.mark_rejected("dedup", "url already seen")
        else:
            job.add_trace("dedup", "passed")
        return job


@register_stage("hard_filter")
class HardFilterStage:
    spec = StageSpec("hard_filter", "reject listings matching the blocklist keywords",
                     requires=["raw_text"], produces=["rejected", "reject_reason"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, profile: Profile) -> None:
        self.patterns = [
            (kw, re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE))
            for kw in profile.blocklist
        ]

    def run(self, job: Job) -> Job:
        for kw, pat in self.patterns:
            if pat.search(job.raw_text):
                job.mark_rejected("hard_filter", f"blocklist: {kw}")
                return job
        job.add_trace("hard_filter", "passed")
        return job


@register_stage("dedup_fuzzy")
class FuzzyDedupStage:
    spec = StageSpec("dedup_fuzzy", "drop cross-source duplicates by company+title",
                     requires=["company", "title"], produces=["fuzzy_key", "rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, seen_index: SeenIndex) -> None:
        self.seen = seen_index

    def run(self, job: Job) -> Job:
        job.fuzzy_key = make_fuzzy_key(job.company, job.title)
        if self.seen.has_fuzzy(job.fuzzy_key):
            job.mark_rejected("dedup_fuzzy", f"duplicate role: {job.fuzzy_key}")
        else:
            job.add_trace("dedup_fuzzy", "passed")
        return job


@register_stage("location")
class LocationStage:
    spec = StageSpec("location", "apply remote/metro rules to the extracted location",
                     requires=["location"], produces=["location_ok", "rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, profile: Profile) -> None:
        self.rules = profile.locations

    def run(self, job: Job) -> Job:
        loc = job.location.lower()
        ok = (self.rules.remote and "remote" in loc) or any(
            metro.lower() in loc for metro in self.rules.allowed_metros
        )
        job.location_ok = ok
        if ok:
            job.add_trace("location", "passed")
        else:
            job.mark_rejected("location", f"location not allowed: {job.location!r}")
        return job


@register_stage("salary")
class SalaryStage:
    spec = StageSpec("salary", "compare extracted comp against the salary floor",
                     requires=["comp_max", "comp_period"], produces=["salary_ok", "rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, profile: Profile) -> None:
        self.floor = profile.salary_floor
        self.not_listed = profile.salary_not_listed

    def run(self, job: Job) -> Job:
        if self.floor is None:
            job.salary_ok = True
            job.add_trace("salary", "no floor configured")
            return job
        if job.comp_max is None:
            if self.not_listed == "reject":
                job.salary_ok = False
                job.mark_rejected("salary", "salary not listed")
            else:
                job.add_trace("salary", "not listed; kept per profile")
            return job
        annual = job.comp_max * (HOURS_PER_YEAR if job.comp_period == "hourly" else 1)
        job.salary_ok = annual >= self.floor
        if job.salary_ok:
            job.add_trace("salary", f"passed ({annual} >= {self.floor})")
        else:
            job.mark_rejected("salary", f"below floor ({annual} < {self.floor})")
        return job
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_rule_stages.py -v` (15 tests)

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: deterministic rule stages (dedup, hard_filter, dedup_fuzzy, location, salary)"`

---

### Task 6: AgentRunner interface + MockRunner

**Files:**
- Create: `job_pipeline/core/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:**
- Produces: `AgentRunner` protocol: `run(prompt: str, model: str, schema: type[BaseModel]) -> BaseModel`; `MockRunner(responses: list[dict])` returning queued dicts validated through the schema, recording `calls: list[tuple[prompt, model]]`; `parse_json_reply(text) -> dict` that tolerates markdown code fences; `RunnerError(Exception)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
import pytest
from pydantic import BaseModel
from job_pipeline.core.runner import MockRunner, parse_json_reply, RunnerError


class Out(BaseModel):
    name: str


def test_mock_runner_returns_validated_schema():
    r = MockRunner([{"name": "acme"}])
    out = r.run("prompt", "haiku", Out)
    assert isinstance(out, Out) and out.name == "acme"
    assert r.calls == [("prompt", "haiku")]


def test_mock_runner_raises_when_exhausted():
    with pytest.raises(RunnerError):
        MockRunner([]).run("p", "haiku", Out)


def test_parse_json_reply_strips_code_fences():
    assert parse_json_reply('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_reply('{"a": 1}') == {"a": 1}


def test_parse_json_reply_raises_on_garbage():
    with pytest.raises(RunnerError):
        parse_json_reply("not json")
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_runner.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/core/runner.py
"""AgentRunner: the swappable seam between stages and any model backend."""
from __future__ import annotations

import json
import re
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class RunnerError(Exception):
    """Raised when a runner cannot produce a valid structured reply."""


class AgentRunner(Protocol):
    def run(self, prompt: str, model: str, schema: type[T]) -> T: ...


def parse_json_reply(text: str) -> dict:
    """Extract a JSON object from a model reply, tolerating ```json fences."""
    stripped = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    candidate = fence.group(1) if fence else stripped
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        raise RunnerError(f"model reply was not valid JSON: {e}") from e


class MockRunner:
    """Test double: returns queued dicts, validated through the requested schema."""

    def __init__(self, responses: list[dict]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def run(self, prompt: str, model: str, schema: type[T]) -> T:
        self.calls.append((prompt, model))
        if not self._responses:
            raise RunnerError("MockRunner exhausted")
        return schema(**self._responses.pop(0))
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_runner.py -v`

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: AgentRunner protocol, MockRunner, JSON reply parsing"`

---

### Task 7: Agent stages — extract, skill_gap, score

**Files:**
- Create: `job_pipeline/stages/agents.py`
- Test: `tests/test_agent_stages.py`

**Interfaces:**
- Consumes: `AgentRunner`, `Profile`, `Job`, registries.
- Produces: registered stages `extract` (ExtractStage(runner, model)), `skill_gap` (SkillGapStage(runner, model, profile)), `score` (ScoreStage(runner, model, profile)). Pydantic reply schemas: `ExtractReply(title, company, location, comp_text, comp_min, comp_max, comp_currency, comp_period, requirements, description, employer_address, employer_phone, employer_email)` (all optional with defaults), `SkillGapReply(have: list[str], missing: list[str], partial: list[str])`, `ScoreReply(score: float [0..100], rationale: str)`. A `RunnerError`/`ValidationError` inside `run()` propagates — the orchestrator (Task 8) owns error isolation.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_agent_stages.py
from datetime import datetime, UTC
from job_pipeline.core.job import Job
from job_pipeline.core.runner import MockRunner
from job_pipeline.config import Profile
from job_pipeline.stages.agents import ExtractStage, SkillGapStage, ScoreStage


def make_job(**kw):
    base = dict(source="t", url="https://x.com/1",
                raw_text="Senior Eng at Acme. $150k-$180k. Python required.",
                fetched_at=datetime.now(UTC))
    base.update(kw)
    return Job(**base)


EXTRACT_REPLY = {
    "title": "Senior Engineer", "company": "Acme", "location": "Remote",
    "comp_text": "$150k-$180k", "comp_min": 150000, "comp_max": 180000,
    "comp_currency": "USD", "comp_period": "annual",
    "requirements": ["python"], "description": "Build things.",
}


def test_extract_maps_reply_onto_job():
    r = MockRunner([EXTRACT_REPLY])
    j = ExtractStage(r, "haiku").run(make_job())
    assert j.company == "Acme" and j.comp_max == 180000
    assert not j.rejected
    prompt, model = r.calls[0]
    assert model == "haiku" and "Senior Eng at Acme" in prompt


def test_skill_gap_stores_dict_and_reads_profile():
    p = Profile(must_have_skills=["python"], body="## Resume\nPython dev")
    r = MockRunner([{"have": ["python"], "missing": ["rust"], "partial": []}])
    j = SkillGapStage(r, "sonnet", p).run(make_job(requirements=["python", "rust"]))
    assert j.skill_gap == {"have": ["python"], "missing": ["rust"], "partial": []}
    assert "Python dev" in r.calls[0][0]      # resume body fed to the agent


def test_score_sets_score_and_rationale():
    p = Profile(body="prefs")
    r = MockRunner([{"score": 87.0, "rationale": "Strong match"}])
    j = ScoreStage(r, "opus", p).run(make_job())
    assert j.score == 87.0 and j.score_rationale == "Strong match"
    assert r.calls[0][1] == "opus"
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_agent_stages.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/stages/agents.py
"""The three agent stages. Prompts are frozen module constants for cache stability."""
from __future__ import annotations

from pydantic import BaseModel, Field

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.core.stage import StageSpec


class ExtractReply(BaseModel):
    title: str = ""
    company: str = ""
    location: str = ""
    comp_text: str = ""
    comp_min: int | None = None
    comp_max: int | None = None
    comp_currency: str | None = None
    comp_period: str | None = None       # "annual" | "hourly"
    requirements: list[str] = []
    description: str = ""
    employer_address: str = ""
    employer_phone: str = ""
    employer_email: str = ""


class SkillGapReply(BaseModel):
    have: list[str] = []
    missing: list[str] = []
    partial: list[str] = []


class ScoreReply(BaseModel):
    score: float = Field(ge=0, le=100)
    rationale: str


EXTRACT_PROMPT = """Extract structured fields from this job listing. Reply with ONLY a JSON object:
{{"title": str, "company": str, "location": str, "comp_text": str,
 "comp_min": int|null, "comp_max": int|null, "comp_currency": str|null,
 "comp_period": "annual"|"hourly"|null, "requirements": [str], "description": str,
 "employer_address": str, "employer_phone": str, "employer_email": str}}
comp_min/comp_max are numbers only (e.g. "$150k" -> 150000). Use "" / null / [] when absent.
description is a 2-3 sentence summary.

LISTING:
{raw_text}"""

SKILL_GAP_PROMPT = """Compare this candidate against the job requirements. Reply with ONLY a JSON object:
{{"have": [str], "missing": [str], "partial": [str]}}

CANDIDATE PROFILE:
{profile_body}

JOB REQUIREMENTS:
{requirements}

JOB DESCRIPTION:
{description}"""

SCORE_PROMPT = """Score this job 0-100 for fit against the candidate's profile and preferences.
Reply with ONLY a JSON object: {{"score": number, "rationale": str}}
The rationale should be 2-4 sentences naming the decisive factors.

CANDIDATE PROFILE AND PREFERENCES:
{profile_body}

JOB: {title} at {company} ({location}) — {comp_text}
DESCRIPTION: {description}
SKILL GAP: {skill_gap}"""


@register_stage("extract")
class ExtractStage:
    spec = StageSpec("extract", "normalize a raw listing into structured fields",
                     requires=["raw_text"],
                     produces=["title", "company", "location", "comp_min", "comp_max"],
                     kind="agent", cost_tier="cheap")

    def __init__(self, runner: AgentRunner, model: str) -> None:
        self.runner, self.model = runner, model

    def run(self, job: Job) -> Job:
        reply = self.runner.run(
            EXTRACT_PROMPT.format(raw_text=job.raw_text), self.model, ExtractReply
        )
        for field_name, value in reply.model_dump().items():
            setattr(job, field_name, value)
        job.add_trace("extract", "extracted")
        return job


@register_stage("skill_gap")
class SkillGapStage:
    spec = StageSpec("skill_gap", "compare resume/skills to job requirements",
                     requires=["requirements", "description"], produces=["skill_gap"],
                     kind="agent", cost_tier="mid")

    def __init__(self, runner: AgentRunner, model: str, profile: Profile) -> None:
        self.runner, self.model, self.profile = runner, model, profile

    def run(self, job: Job) -> Job:
        reply = self.runner.run(
            SKILL_GAP_PROMPT.format(
                profile_body=self.profile.body,
                requirements=job.requirements,
                description=job.description,
            ),
            self.model, SkillGapReply,
        )
        job.skill_gap = reply.model_dump()
        job.add_trace("skill_gap", "analyzed")
        return job


@register_stage("score")
class ScoreStage:
    spec = StageSpec("score", "final fit judgment with rationale",
                     requires=["title", "company", "description", "skill_gap"],
                     produces=["score", "score_rationale"],
                     kind="agent", cost_tier="expensive")

    def __init__(self, runner: AgentRunner, model: str, profile: Profile) -> None:
        self.runner, self.model, self.profile = runner, model, profile

    def run(self, job: Job) -> Job:
        reply = self.runner.run(
            SCORE_PROMPT.format(
                profile_body=self.profile.body,
                title=job.title, company=job.company, location=job.location,
                comp_text=job.comp_text, description=job.description,
                skill_gap=job.skill_gap,
            ),
            self.model, ScoreReply,
        )
        job.score, job.score_rationale = reply.score, reply.rationale
        job.add_trace("score", f"scored {reply.score}")
        return job
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_agent_stages.py -v`

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: agent stages (extract, skill_gap, score) with pydantic reply schemas"`

---

### Task 8: Deterministic orchestrator

**Files:**
- Create: `job_pipeline/core/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `Stage`, `Job`, `StageSpec`.
- Produces: `Orchestrator` protocol (`run(jobs, stages) -> RunResult`); `DeterministicOrchestrator(max_agent_jobs=None)`; `RunResult(processed: list[Job], deferred: list[Job])`. Semantics: walks stages in order per job; short-circuits on `rejected`/`errored`; any exception in a stage → `job.mark_errored(stage_name, str(exc))` and the run continues; **agent cap** counts jobs that reach their FIRST `kind=="agent"` stage — beyond the cap the job is *deferred* (not marked seen, not processed further, reported separately), FIFO by input order.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
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
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_orchestrator.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/core/orchestrator.py
"""Deterministic orchestrator. Swappable: an AgentOrchestrator can implement
the same protocol later using StageSpec catalogs and Job.trace."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence

from job_pipeline.core.job import Job
from job_pipeline.core.stage import Stage


@dataclass
class RunResult:
    processed: list[Job] = field(default_factory=list)
    deferred: list[Job] = field(default_factory=list)


class Orchestrator(Protocol):
    def run(self, jobs: Sequence[Job], stages: Sequence[Stage]) -> RunResult: ...


class DeterministicOrchestrator:
    def __init__(self, max_agent_jobs: int | None = None) -> None:
        self.max_agent_jobs = max_agent_jobs

    def run(self, jobs: Sequence[Job], stages: Sequence[Stage]) -> RunResult:
        result = RunResult()
        agent_slots_used = 0
        for job in jobs:
            deferred = False
            for stage in stages:
                if job.rejected or job.errored:
                    break
                if stage.spec.kind == "agent" and not self._entered_agent(job):
                    if (self.max_agent_jobs is not None
                            and agent_slots_used >= self.max_agent_jobs):
                        deferred = True
                        break
                    agent_slots_used += 1
                    job._entered_agent = True   # per-run marker, not persisted
                try:
                    job = stage.run(job)
                except Exception as exc:  # noqa: BLE001 — per-job isolation
                    job.mark_errored(stage.spec.name, str(exc))
            (result.deferred if deferred else result.processed).append(job)
        return result

    @staticmethod
    def _entered_agent(job: Job) -> bool:
        return getattr(job, "_entered_agent", False)
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_orchestrator.py -v`

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: deterministic orchestrator with error isolation and agent cap"`

---

### Task 9: Obsidian writer + publish stage

**Files:**
- Create: `job_pipeline/store/obsidian.py`, `job_pipeline/stages/publish.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `Job`, `StageSpec`, registry.
- Produces: `ObsidianWriter(vault: Path)` with `write(job) -> Path` and `is_user_touched(job_id) -> bool`; registered stage `publish` (PublishStage(writer, force=False)). Note filename: `{company-slug}-{title-slug}-{job.id[:8]}.md` (slug: lowercase alnum/hyphens). Frontmatter keys exactly: `company, position, employer_address, employer_phone, employer_email, employer_contact_person, date_found, date_of_contact, source_url, type_of_work, result_of_contact, score, status, job_id`. New notes: `status: to_review`, `result_of_contact: found`, empty `date_of_contact`/`employer_contact_person`. **Skip-on-edit:** if the note exists and its `status` != `to_review`, publish skips unless `force=True`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publish.py
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
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_publish.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/store/obsidian.py
"""Writes one Obsidian note per job; frontmatter doubles as the VEC record."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from job_pipeline.core.job import Job


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "unknown"


class ObsidianWriter:
    def __init__(self, vault: Path) -> None:
        self.vault = Path(vault).expanduser()
        self.vault.mkdir(parents=True, exist_ok=True)

    def path_for(self, job: Job) -> Path:
        return self.vault / f"{_slug(job.company)}-{_slug(job.title)}-{job.id[:8]}.md"

    def is_user_touched(self, job: Job) -> bool:
        path = self.path_for(job)
        if not path.exists():
            return False
        text = path.read_text()
        try:
            _, fm, _ = text.split("---", 2)
            return (yaml.safe_load(fm) or {}).get("status") != "to_review"
        except ValueError:
            return True   # malformed note: treat as user-owned, never clobber

    def write(self, job: Job) -> Path:
        frontmatter = {
            "company": job.company,
            "position": job.title,
            "employer_address": job.employer_address,
            "employer_phone": job.employer_phone,
            "employer_email": job.employer_email,
            "employer_contact_person": "",
            "date_found": job.fetched_at.date().isoformat(),
            "date_of_contact": "",
            "source_url": job.url,
            "type_of_work": job.title,
            "result_of_contact": "found",
            "score": job.score,
            "status": "to_review",
            "job_id": job.id,
        }
        gap = job.skill_gap or {}
        body = (
            f"## Fit — {job.score}/100\n{job.score_rationale}\n\n"
            f"## Skill gap\n"
            f"- Have: {', '.join(gap.get('have', []))}\n"
            f"- Missing: {', '.join(gap.get('missing', []))}\n"
            f"- Partial: {', '.join(gap.get('partial', []))}\n\n"
            f"## Description\n{job.description}\n"
        )
        path = self.path_for(job)
        path.write_text(
            "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body
        )
        return path
```

```python
# job_pipeline/stages/publish.py
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.store.obsidian import ObsidianWriter


@register_stage("publish")
class PublishStage:
    spec = StageSpec("publish", "write the Obsidian note (VEC-ready frontmatter)",
                     requires=["title", "company", "score"], produces=[],
                     kind="deterministic", cost_tier="free")

    def __init__(self, writer: ObsidianWriter, force: bool = False) -> None:
        self.writer, self.force = writer, force

    def run(self, job: Job) -> Job:
        if not self.force and self.writer.is_user_touched(job):
            job.add_trace("publish", "skipped: note edited by user")
            return job
        path = self.writer.write(job)
        job.add_trace("publish", f"wrote {path.name}")
        return job
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_publish.py -v`

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: Obsidian note writer with VEC frontmatter and skip-on-edit publish"`

---

### Task 10: Sources — base, manual (inbox + --url), RSS, Greenhouse, Lever

**Files:**
- Create: `job_pipeline/sources/__init__.py`, `job_pipeline/sources/base.py`, `job_pipeline/sources/manual.py`, `job_pipeline/sources/feeds.py`
- Create: `tests/fixtures/jobs.rss` (fixture), `tests/fixtures/greenhouse.json`, `tests/fixtures/lever.json`
- Test: `tests/test_sources.py`

**Interfaces:**
- Consumes: `Job`, registries.
- Produces: `Source` protocol: `fetch() -> list[Job]` and `on_terminal(job) -> None` (no-op default; manual source uses it to consume inbox lines). Registered sources: `manual` (`ManualSource(inbox: Path|None, urls: list[str])` — fetches each URL's page text via `httpx.get` with a 20s timeout, `raw_text` = response text; inbox lines are removed only when `on_terminal` is called for that URL), `rss` (`RssSource(url)` via feedparser — one Job per entry, `raw_text` = title + summary), `greenhouse` (`GreenhouseSource(board)` — GET `https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true`), `lever` (`LeverSource(org)` — GET `https://api.lever.co/v0/postings/{org}?mode=json`). All network calls isolated in a `_get(url) -> str|dict` helper monkeypatched in tests.

- [ ] **Step 1: Create fixtures**

`tests/fixtures/jobs.rss`:
```xml
<?xml version="1.0"?>
<rss version="2.0"><channel><title>Jobs</title>
<item><title>Backend Engineer - Acme</title>
<link>https://example.com/jobs/1</link>
<description>Python backend role, remote, $150k+</description></item>
<item><title>Web3 Wizard - ChainCo</title>
<link>https://example.com/jobs/2</link>
<description>Crypto trading platform</description></item>
</channel></rss>
```

`tests/fixtures/greenhouse.json`:
```json
{"jobs": [{"id": 1, "title": "Platform Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "location": {"name": "Remote"}, "content": "Build our platform. Python required."}]}
```

`tests/fixtures/lever.json`:
```json
[{"id": "ab1", "text": "SRE", "hostedUrl": "https://jobs.lever.co/acme/ab1", "categories": {"location": "Richmond, VA"}, "descriptionPlain": "Keep the lights on."}]
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_sources.py
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
```

- [ ] **Step 3: Run to verify FAIL** — `pytest tests/test_sources.py -v`

- [ ] **Step 4: Implement**

```python
# job_pipeline/sources/base.py
from __future__ import annotations

from typing import Protocol

import httpx

from job_pipeline.core.job import Job


class Source(Protocol):
    def fetch(self) -> list[Job]: ...
    def on_terminal(self, job: Job) -> None: ...


def http_get_text(url: str) -> str:
    resp = httpx.get(url, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def http_get_json(url: str):
    resp = httpx.get(url, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()
```

```python
# job_pipeline/sources/manual.py
"""User-fed URLs: repeatable --url flags plus a plaintext inbox file (a queue)."""
from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_source
from job_pipeline.sources.base import http_get_text


@register_source("manual")
class ManualSource:
    def __init__(self, inbox: Path | str | None = None, urls: list[str] | None = None) -> None:
        self.inbox = Path(inbox).expanduser() if inbox else None
        self.urls = urls or []
        self._get = http_get_text
        self._inbox_urls: set[str] = set()

    def _read_inbox(self) -> list[str]:
        if not self.inbox or not self.inbox.exists():
            return []
        return [ln.strip() for ln in self.inbox.read_text().splitlines() if ln.strip()]

    def fetch(self) -> list[Job]:
        inbox_urls = self._read_inbox()
        self._inbox_urls = set(inbox_urls)
        jobs = []
        for url in [*inbox_urls, *self.urls]:
            job = Job(source="manual", url=url, raw_text="", fetched_at=datetime.now(UTC))
            try:
                job.raw_text = self._get(url)
            except Exception as exc:  # noqa: BLE001 — a dead URL degrades one job
                job.mark_errored("manual_fetch", str(exc))
            jobs.append(job)
        return jobs

    def on_terminal(self, job: Job) -> None:
        """Remove the job's line from the inbox once it is published or rejected."""
        if not self.inbox or job.url not in self._inbox_urls:
            return
        lines = [ln for ln in self._read_inbox() if ln != job.url]
        self.inbox.write_text("".join(f"{ln}\n" for ln in lines))
```

```python
# job_pipeline/sources/feeds.py
"""API-friendly pull sources: RSS, Greenhouse boards, Lever postings."""
from __future__ import annotations

from datetime import datetime, UTC

import feedparser

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_source
from job_pipeline.sources.base import http_get_json, http_get_text


@register_source("rss")
class RssSource:
    def __init__(self, url: str) -> None:
        self.url = url
        self._get = http_get_text

    def fetch(self) -> list[Job]:
        feed = feedparser.parse(self._get(self.url))
        return [
            Job(source="rss", url=e.link,
                raw_text=f"{e.get('title', '')}\n{e.get('summary', '')}",
                fetched_at=datetime.now(UTC))
            for e in feed.entries
        ]

    def on_terminal(self, job: Job) -> None: ...


@register_source("greenhouse")
class GreenhouseSource:
    def __init__(self, board: str) -> None:
        self.board = board
        self._get = http_get_json

    def fetch(self) -> list[Job]:
        data = self._get(
            f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        )
        jobs = []
        for item in data.get("jobs", []):
            j = Job(source="greenhouse", url=item["absolute_url"],
                    raw_text=f"{item.get('title', '')}\n{item.get('content', '')}",
                    fetched_at=datetime.now(UTC))
            j.title = item.get("title", "")
            j.location = (item.get("location") or {}).get("name", "")
            jobs.append(j)
        return jobs

    def on_terminal(self, job: Job) -> None: ...


@register_source("lever")
class LeverSource:
    def __init__(self, org: str) -> None:
        self.org = org
        self._get = http_get_json

    def fetch(self) -> list[Job]:
        data = self._get(f"https://api.lever.co/v0/postings/{self.org}?mode=json")
        jobs = []
        for item in data:
            j = Job(source="lever", url=item["hostedUrl"],
                    raw_text=f"{item.get('text', '')}\n{item.get('descriptionPlain', '')}",
                    fetched_at=datetime.now(UTC))
            j.title = item.get("text", "")
            j.location = (item.get("categories") or {}).get("location", "")
            jobs.append(j)
        return jobs

    def on_terminal(self, job: Job) -> None: ...
```

- [ ] **Step 5: Run to verify PASS** — `pytest tests/test_sources.py -v`

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: manual/rss/greenhouse/lever sources with transactional inbox"`

---

### Task 11: `existing_vault` seeder

**Files:**
- Create: `job_pipeline/seeders/__init__.py`, `job_pipeline/seeders/existing_vault.py`
- Test: `tests/test_seeder.py`

**Interfaces:**
- Consumes: `SeenIndex`, `make_fuzzy_key`, registry.
- Produces: registered seeder `existing_vault` — `ExistingVaultSeeder(path, url_field="source_url", company_field="company", title_field="position")` with `seed(seen_index) -> int` (returns count). Reads every `*.md` in the vault, parses frontmatter, marks `hash(url)` + fuzzy key. Notes without frontmatter or the URL field are skipped silently.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_seeder.py
import hashlib
from job_pipeline.store.seen_index import SeenIndex
from job_pipeline.seeders.existing_vault import ExistingVaultSeeder

NOTE = """---
company: "Acme Corp"
position: "Senior Engineer"
source_url: "https://x.com/jobs/1"
---
body
"""


def url_hash(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def test_seed_marks_url_and_fuzzy_key(tmp_path):
    (tmp_path / "note.md").write_text(NOTE)
    (tmp_path / "not-a-job.md").write_text("no frontmatter")
    idx = SeenIndex(tmp_path / "seen.sqlite")
    count = ExistingVaultSeeder(path=tmp_path).seed(idx)
    assert count == 1
    assert idx.has_url(url_hash("https://x.com/jobs/1"))
    assert idx.has_fuzzy("acmecorp|seniorengineer")


def test_custom_field_mapping(tmp_path):
    (tmp_path / "n.md").write_text('---\nlink: "https://y.com/2"\n---\nx')
    idx = SeenIndex(tmp_path / "seen.sqlite")
    assert ExistingVaultSeeder(path=tmp_path, url_field="link").seed(idx) == 1
    assert idx.has_url(url_hash("https://y.com/2"))
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_seeder.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/seeders/existing_vault.py
"""Opt-in seeder: pre-populate the seen-index from an existing Obsidian job vault."""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from job_pipeline.core.registry import register_seeder
from job_pipeline.stages.rules import make_fuzzy_key
from job_pipeline.store.seen_index import SeenIndex


@register_seeder("existing_vault")
class ExistingVaultSeeder:
    def __init__(self, path: Path | str, url_field: str = "source_url",
                 company_field: str = "company", title_field: str = "position") -> None:
        self.path = Path(path).expanduser()
        self.url_field = url_field
        self.company_field = company_field
        self.title_field = title_field

    def seed(self, seen_index: SeenIndex) -> int:
        count = 0
        for note in self.path.glob("*.md"):
            text = note.read_text()
            if not text.startswith("---"):
                continue
            try:
                _, fm, _ = text.split("---", 2)
                data = yaml.safe_load(fm) or {}
            except (ValueError, yaml.YAMLError):
                continue
            url = data.get(self.url_field)
            if not url:
                continue
            url_hash = hashlib.sha256(str(url).encode()).hexdigest()[:16]
            fuzzy = make_fuzzy_key(
                str(data.get(self.company_field, "")), str(data.get(self.title_field, ""))
            )
            seen_index.mark(url_hash, fuzzy if fuzzy != "|" else "")
            count += 1
        return count
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_seeder.py -v`

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: existing_vault seeder pre-populates dedup index"`

---

### Task 12: SDK runner (Claude Agent SDK, subscription auth)

**Files:**
- Create: `job_pipeline/core/sdk_runner.py`
- Test: `tests/test_sdk_runner.py` (unit: guard + retry logic, mocked transport) and one `@pytest.mark.integration` test.

**Interfaces:**
- Consumes: `parse_json_reply`, `RunnerError`.
- Produces: `SDKRunner(max_attempts=3)` implementing `AgentRunner`. Behavior: (1) constructor raises `RuntimeError` if `ANTHROPIC_API_KEY` is set (billing guard per Global Constraints); (2) `run()` calls `self._query(prompt, model) -> str` (the seam holding all SDK/async plumbing), parses with `parse_json_reply`, validates with the schema, retries up to `max_attempts` on `RunnerError`/`ValidationError`, then raises `RunnerError`.

**Implementation note:** verify the exact `claude_agent_sdk` API against the installed package before writing `_query` (`python -c "import claude_agent_sdk; help(claude_agent_sdk.query)"`). The shape below is the expected one; adjust names to what the installed version exposes, keeping the `_query` seam identical.

- [ ] **Step 1: Write the failing unit tests**

```python
# tests/test_sdk_runner.py
import pytest
from pydantic import BaseModel
from job_pipeline.core.runner import RunnerError
from job_pipeline.core.sdk_runner import SDKRunner


class Out(BaseModel):
    name: str


def test_refuses_to_run_with_api_key_set(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-xxx")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        SDKRunner()


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = SDKRunner(max_attempts=3)
    replies = iter(["garbage", '{"name": "acme"}'])
    r._query = lambda prompt, model: next(replies)
    out = r.run("p", "haiku", Out)
    assert out.name == "acme"


def test_raises_after_max_attempts(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = SDKRunner(max_attempts=2)
    r._query = lambda prompt, model: "never json"
    with pytest.raises(RunnerError):
        r.run("p", "haiku", Out)


@pytest.mark.integration
def test_real_sdk_roundtrip(monkeypatch):
    """Opt-in: pytest -m integration. Requires logged-in Claude Code."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = SDKRunner().run(
        'Reply with ONLY this JSON object: {"name": "test"}', "haiku", Out
    )
    assert out.name == "test"
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_sdk_runner.py -v` (integration test auto-excluded)

- [ ] **Step 3: Implement**

```python
# job_pipeline/core/sdk_runner.py
"""AgentRunner backed by the Claude Agent SDK (rides Claude Code subscription auth).

Billing guard: a set ANTHROPIC_API_KEY silently flips the SDK to pay-as-you-go
API credits. This project is subscription-only, so we refuse to start.
"""
from __future__ import annotations

import os
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from job_pipeline.core.runner import RunnerError, parse_json_reply

T = TypeVar("T", bound=BaseModel)

SYSTEM_PROMPT = (
    "You are a data-processing engine inside a pipeline. "
    "Reply with ONLY the requested JSON object — no prose, no markdown."
)


class SDKRunner:
    def __init__(self, max_attempts: int = 3) -> None:
        if os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is set — this would bill API credits instead of "
                "your subscription. Unset it (subscription auth comes from your "
                "logged-in Claude Code session)."
            )
        self.max_attempts = max_attempts

    def run(self, prompt: str, model: str, schema: type[T]) -> T:
        last_err: Exception | None = None
        for _ in range(self.max_attempts):
            try:
                reply = self._query(prompt, model)
                return schema(**parse_json_reply(reply))
            except (RunnerError, ValidationError) as e:
                last_err = e
        raise RunnerError(f"no valid reply after {self.max_attempts} attempts: {last_err}")

    def _query(self, prompt: str, model: str) -> str:
        """All SDK/async plumbing lives here — the seam mocked in unit tests."""
        import anyio
        from claude_agent_sdk import (
            AssistantMessage, ClaudeAgentOptions, TextBlock, query,
        )

        async def go() -> str:
            options = ClaudeAgentOptions(
                model=model,
                system_prompt=SYSTEM_PROMPT,
                max_turns=1,
                allowed_tools=[],
            )
            text = ""
            async for message in query(prompt=prompt, options=options):
                if isinstance(message, AssistantMessage):
                    for block in message.content:
                        if isinstance(block, TextBlock):
                            text += block.text
            return text

        return anyio.run(go)
```

- [ ] **Step 4: Run unit tests** — `pytest tests/test_sdk_runner.py -v` → 3 PASS, 1 deselected

- [ ] **Step 5: Run the integration test once, manually** — `pytest -m integration -v`
Expected: PASS (requires logged-in Claude Code, spends a few Haiku tokens). If the SDK API differs from the expected shape, fix `_query` only and re-run.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: Claude Agent SDK runner with subscription billing guard"`

---

### Task 13: Pipeline assembly + CLI

**Files:**
- Create: `job_pipeline/core/pipeline.py`, `job_pipeline/cli.py`
- Test: `tests/test_pipeline_e2e.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `build_stages(cfg: PipelineConfig, profile: Profile, seen: SeenIndex, runner: AgentRunner, writer: ObsidianWriter, force=False) -> list[Stage]` (instantiates each configured stage name with its dependencies; agent stages get `cfg.models[name]`); `run_pipeline(cfg, profile, runner, extra_urls=None, force=False, db_path=None) -> RunSummary` which: seeds seeders → fetches all sources (each guarded; a dead source logs and continues) → runs `DeterministicOrchestrator(cfg.limits.max_agent_jobs_per_run)` → marks terminal jobs (published or rejected, NOT errored/deferred) in the seen-index → calls each source's `on_terminal` for its terminal jobs → returns `RunSummary(published, rejected, errored, deferred: int, notes: list[Path])`. CLI: `job-pipeline run [--config PATH] [--profile PATH] [--url URL ...] [--force] [--mock]` printing the summary (`--mock` uses MockRunner with canned replies for dry runs).

- [ ] **Step 1: Write the failing end-to-end test**

```python
# tests/test_pipeline_e2e.py
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
```

- [ ] **Step 2: Run to verify FAIL** — `pytest tests/test_pipeline_e2e.py -v`

- [ ] **Step 3: Implement**

```python
# job_pipeline/core/pipeline.py
"""Wires config -> stages/sources/seeders and runs one batch."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from job_pipeline.config import PipelineConfig, Profile
from job_pipeline.core.job import Job
from job_pipeline.core.orchestrator import DeterministicOrchestrator
from job_pipeline.core.registry import get_seeder, get_source, get_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.store.obsidian import ObsidianWriter
from job_pipeline.store.seen_index import SeenIndex

# side-effect imports: populate the registries
import job_pipeline.stages.rules      # noqa: F401
import job_pipeline.stages.agents     # noqa: F401
import job_pipeline.stages.publish    # noqa: F401
import job_pipeline.sources.manual    # noqa: F401
import job_pipeline.sources.feeds     # noqa: F401
import job_pipeline.seeders.existing_vault  # noqa: F401

log = logging.getLogger("job_pipeline")


@dataclass
class RunSummary:
    published: int = 0
    rejected: int = 0
    errored: int = 0
    deferred: int = 0
    notes: list[Path] = field(default_factory=list)


def build_stages(cfg: PipelineConfig, profile: Profile, seen: SeenIndex,
                 runner: AgentRunner, writer: ObsidianWriter, force: bool = False):
    deps = {
        "dedup": lambda c: c(seen),
        "hard_filter": lambda c: c(profile),
        "dedup_fuzzy": lambda c: c(seen),
        "location": lambda c: c(profile),
        "salary": lambda c: c(profile),
        "extract": lambda c: c(runner, cfg.models["extract"]),
        "skill_gap": lambda c: c(runner, cfg.models["skill_gap"], profile),
        "score": lambda c: c(runner, cfg.models["score"], profile),
        "publish": lambda c: c(writer, force),
    }
    stages = []
    for name in cfg.stages:
        cls = get_stage(name)
        stages.append(deps[name](cls) if name in deps else cls())
    return stages


def build_sources(cfg: PipelineConfig, extra_urls: list[str] | None = None):
    sources = []
    manual_seen = False
    for spec in cfg.sources:
        spec = dict(spec)
        kind = spec.pop("type")
        if kind == "manual":
            spec["urls"] = extra_urls or []
            manual_seen = True
        sources.append(get_source(kind)(**spec))
    if extra_urls and not manual_seen:
        sources.append(get_source("manual")(urls=extra_urls))
    return sources


def run_pipeline(cfg: PipelineConfig, profile: Profile, runner: AgentRunner,
                 sources=None, extra_urls: list[str] | None = None,
                 force: bool = False, db_path: Path | None = None) -> RunSummary:
    db = db_path or cfg.output.vault.expanduser() / ".job_pipeline.seen.sqlite"
    seen = SeenIndex(db)
    writer = ObsidianWriter(cfg.output.vault)

    for spec in cfg.seeders:
        spec = dict(spec)
        kind = spec.pop("type")
        n = get_seeder(kind)(**spec).seed(seen)
        log.info("seeder %s marked %d jobs", kind, n)

    if sources is None:
        sources = build_sources(cfg, extra_urls)

    jobs: list[Job] = []
    origin: dict[str, object] = {}
    for src in sources:
        try:
            fetched = src.fetch()
        except Exception as exc:  # noqa: BLE001 — one dead feed doesn't kill the run
            log.warning("source %s failed: %s", type(src).__name__, exc)
            continue
        for j in fetched:
            origin[j.id] = src
            jobs.append(j)

    stages = build_stages(cfg, profile, seen, runner, writer, force)
    result = DeterministicOrchestrator(cfg.limits.max_agent_jobs_per_run).run(jobs, stages)

    summary = RunSummary(deferred=len(result.deferred))
    for job in result.processed:
        if job.errored:
            summary.errored += 1
            continue                      # stays unseen -> retries next run
        if job.rejected:
            summary.rejected += 1
        else:
            summary.published += 1
            summary.notes.append(writer.path_for(job))
        seen.mark(job.id, job.fuzzy_key)  # terminal only
        src = origin.get(job.id)
        if src is not None:
            src.on_terminal(job)
    if summary.deferred:
        log.warning("%d jobs deferred by agent cap; they retry next run", summary.deferred)
    return summary
```

```python
# job_pipeline/cli.py
"""job-pipeline run — the on-demand (and cron-able) entrypoint."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from job_pipeline.config import load_pipeline_config, load_profile
from job_pipeline.core.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job-pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run the pipeline once")
    run.add_argument("--config", type=Path, default=Path("config/pipeline.yaml"))
    run.add_argument("--profile", type=Path, default=Path("config/profile.md"))
    run.add_argument("--url", action="append", default=[], help="feed a job URL (repeatable)")
    run.add_argument("--force", action="store_true", help="overwrite user-edited notes")
    run.add_argument("--mock", action="store_true", help="dry run with a mock agent")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_pipeline_config(args.config)      # fail fast, before any tokens
    profile = load_profile(args.profile)

    if args.mock:
        from job_pipeline.core.runner import MockRunner
        runner = MockRunner([])   # agent stages will error-isolate per job
    else:
        from job_pipeline.core.sdk_runner import SDKRunner
        runner = SDKRunner()

    s = run_pipeline(cfg, profile, runner, extra_urls=args.url, force=args.force)
    print(f"published={s.published} rejected={s.rejected} "
          f"errored={s.errored} deferred={s.deferred}")
    for note in s.notes:
        print(f"  -> {note}")
    return 0
```

- [ ] **Step 4: Run to verify PASS** — `pytest tests/test_pipeline_e2e.py -v`, then the whole suite: `pytest -v` (all green)

- [ ] **Step 5: Smoke-test the CLI** — `job-pipeline run --config config/pipeline.example.yaml --profile config/profile.example.md --mock`
Expected: exits 0 with a `published=0 ...` summary (example sources fail gracefully or return nothing; no crash).

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: pipeline assembly, run summary, and CLI entrypoint"`

---

### Task 14: README + final verification

**Files:**
- Create: `README.md`
- Modify: `.gitignore` (verify `config/profile.md`, `config/pipeline.yaml` covered — they are)

- [ ] **Step 1: Write README.md** covering: what it is (one paragraph + the stage diagram from the spec §3), quickstart (`python -m venv` → `pip install -e .` → copy the two example configs → `claude` login note → `job-pipeline run`), the three extensibility seams (config-driven stages, registries, personal-data-outside-repo), the subscription-billing guard (`ANTHROPIC_API_KEY` must be unset), VEC note semantics (which fields the user fills on apply), and how to run tests (`pytest`; `pytest -m integration` for the real-SDK test). Pull wording from the spec — do not invent new behavior.

- [ ] **Step 2: Full suite + example-config validation**

Run: `pytest -v` — Expected: all green, integration deselected.
Run: `python3 -c "from job_pipeline.config import load_profile, load_pipeline_config; load_profile('config/profile.example.md'); load_pipeline_config('config/pipeline.example.yaml'); print('examples valid')"`
Expected: `examples valid`

- [ ] **Step 3: Verify no personal data staged** — `git status --short` must show no `config/profile.md`, `config/pipeline.yaml`, or `*.sqlite`.

- [ ] **Step 4: Commit** — `git add -A && git commit -m "docs: README with quickstart, extensibility seams, VEC semantics"`

---

## Self-Review Notes

- **Spec coverage:** intake/manual inbox (T10, T13), dedup + fuzzy dedup (T4, T5), hard filter (T5), extract w/ numeric comp (T7), location/salary (T5), skill-gap/score (T7), publish + VEC + skip-on-edit (T9), orchestrator + error isolation + cap FIFO-defer semantics (T8, T13), seeder (T11), SDK runner + billing guard (T12), config fail-fast + examples (T3), CLI + `--url`/`--force`/`--mock` (T13), publish-safety (T14). Spec §5 (AgentOrchestrator) is future work by design — the `Orchestrator` protocol + `StageSpec` + `trace` land in T2/T8.
- **Deliberate deviation from spec §10:** the SDK's exact query API is verified at Task 12 Step 5 (opt-in integration test) rather than researched up front; `_query` is the only file touched if it differs.
- **Type consistency check:** `Job` field names used by stages (T5/T7/T9) match T1; `StageSpec` positional order (name, purpose, requires, produces, kind, cost_tier) consistent across T2/T5/T7/T9; `SeenIndex.mark(url_hash, fuzzy_key)` consistent T4/T5/T11/T13.
