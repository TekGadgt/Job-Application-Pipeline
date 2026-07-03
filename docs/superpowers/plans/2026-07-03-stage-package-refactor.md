# Stage Package Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `job_pipeline/stages/rules.py` and `job_pipeline/stages/agents.py` into packages with one stage per module, with zero behavior change and zero test edits.

**Architecture:** Each stage moves verbatim into its own module; shared helpers move to a `common.py` per package; each package `__init__.py` imports every submodule (so `@register_stage` side-effects still fire on `import job_pipeline.stages.rules` / `.agents`) and re-exports all public names so existing import paths keep working byte-for-byte.

**Tech Stack:** Python ≥3.11, pytest. No new dependencies.

## Global Constraints

- **Zero test edits.** The full suite must pass with no diff under `tests/`. If a test needs editing, the refactor is wrong. Current baseline: `pytest -q` → `71 passed, 1 deselected`.
- **Import paths must not change for consumers.** These must keep working verbatim:
  - `from job_pipeline.stages.rules import make_fuzzy_key` (used by `job_pipeline/seeders/existing_vault.py:10`)
  - `from job_pipeline.stages.rules import DedupStage, HardFilterStage, FuzzyDedupStage, LocationStage, SalaryStage, make_fuzzy_key`
  - `from job_pipeline.stages.agents import ExtractStage, SkillGapStage, ScoreStage`
  - `ExtractReply`, `SkillGapReply`, `ScoreReply`, `EXTRACT_PROMPT`, `SKILL_GAP_PROMPT`, `SCORE_PROMPT`, and `_fill` importable from `job_pipeline.stages.agents`.
- **Registration side-effects must still fire:** `job_pipeline/core/pipeline.py:17-18` does `import job_pipeline.stages.rules` / `import job_pipeline.stages.agents` to populate the stage registry.
- All code moves **verbatim** — no renames of classes, registry names, or config keys; no logic edits; no docstring rewrites beyond a one-line module docstring per new file.
- A module named `rules.py` and a package `rules/` must never coexist in a commit — create the package and `git rm` the old file in the same commit.
- Do NOT modify `job_pipeline/stages/publish.py`, `job_pipeline/stages/__init__.py`, or anything under `job_pipeline/core/`.

---

### Task 1: Split `stages/rules.py` into the `stages/rules/` package

**Files:**
- Create: `job_pipeline/stages/rules/__init__.py`
- Create: `job_pipeline/stages/rules/common.py`
- Create: `job_pipeline/stages/rules/dedup.py`
- Create: `job_pipeline/stages/rules/hard_filter.py`
- Create: `job_pipeline/stages/rules/dedup_fuzzy.py`
- Create: `job_pipeline/stages/rules/location.py`
- Create: `job_pipeline/stages/rules/salary.py`
- Delete: `job_pipeline/stages/rules.py`
- Test: none (existing `tests/test_rule_stages.py` is the gate and must not change)

**Interfaces:**
- Consumes: existing `Job`, `StageSpec`, `register_stage`, `SeenIndex`, `Profile` — unchanged.
- Produces: package `job_pipeline.stages.rules` exporting exactly `HOURS_PER_YEAR`, `make_fuzzy_key`, `DedupStage`, `HardFilterStage`, `FuzzyDedupStage`, `LocationStage`, `SalaryStage`. Task 2 mirrors this pattern for agents.

- [ ] **Step 1: Confirm the green baseline**

Run: `.venv/bin/pytest -q`
Expected: `71 passed, 1 deselected`

- [ ] **Step 2: Create `job_pipeline/stages/rules/common.py`**

```python
"""Helpers shared by more than one rule stage."""
from __future__ import annotations

import re

HOURS_PER_YEAR = 2080


def make_fuzzy_key(company: str, title: str) -> str:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return f"{norm(company)}|{norm(title)}"
```

- [ ] **Step 3: Create `job_pipeline/stages/rules/dedup.py`**

```python
"""Drop jobs whose URL was already seen."""
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.store.seen_index import SeenIndex


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
```

- [ ] **Step 4: Create `job_pipeline/stages/rules/hard_filter.py`**

```python
"""Reject listings matching the profile's blocklist keywords."""
from __future__ import annotations

import re

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec


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
```

- [ ] **Step 5: Create `job_pipeline/stages/rules/dedup_fuzzy.py`**

```python
"""Drop cross-source duplicates by normalized company+title."""
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.rules.common import make_fuzzy_key
from job_pipeline.store.seen_index import SeenIndex


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
```

- [ ] **Step 6: Create `job_pipeline/stages/rules/location.py`**

```python
"""Apply remote/metro rules to the extracted location."""
from __future__ import annotations

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec


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
```

- [ ] **Step 7: Create `job_pipeline/stages/rules/salary.py`**

```python
"""Compare extracted comp against the profile's salary floor."""
from __future__ import annotations

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.rules.common import HOURS_PER_YEAR


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
                job.salary_ok = True
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

- [ ] **Step 8: Create `job_pipeline/stages/rules/__init__.py`**

Importing the package imports every stage module, so `@register_stage` fires exactly as the old flat module did, and every public name re-exports from its old path.

```python
"""The free deterministic filter stages. No model tokens are spent here."""
from job_pipeline.stages.rules.common import HOURS_PER_YEAR, make_fuzzy_key
from job_pipeline.stages.rules.dedup import DedupStage
from job_pipeline.stages.rules.dedup_fuzzy import FuzzyDedupStage
from job_pipeline.stages.rules.hard_filter import HardFilterStage
from job_pipeline.stages.rules.location import LocationStage
from job_pipeline.stages.rules.salary import SalaryStage

__all__ = [
    "HOURS_PER_YEAR",
    "make_fuzzy_key",
    "DedupStage",
    "FuzzyDedupStage",
    "HardFilterStage",
    "LocationStage",
    "SalaryStage",
]
```

- [ ] **Step 9: Delete the old flat module**

```bash
git rm job_pipeline/stages/rules.py
```

Also clear stale bytecode so the deleted module can't shadow the package:

```bash
find . -name __pycache__ -type d -prune -exec rm -rf {} +
```

- [ ] **Step 10: Run the full suite and verify zero test edits**

Run: `.venv/bin/pytest -q`
Expected: `71 passed, 1 deselected`

Run: `git status --porcelain tests/`
Expected: no output (nothing under `tests/` changed)

- [ ] **Step 11: Commit**

```bash
git add job_pipeline/stages/rules/
git commit -m "refactor: split stages/rules.py into one-module-per-stage package"
```

(The `git rm` from Step 9 is already staged; this commit removes the flat module and adds the package atomically.)

---

### Task 2: Split `stages/agents.py` into the `stages/agents/` package + README template pointer

**Files:**
- Create: `job_pipeline/stages/agents/__init__.py`
- Create: `job_pipeline/stages/agents/common.py`
- Create: `job_pipeline/stages/agents/extract.py`
- Create: `job_pipeline/stages/agents/skill_gap.py`
- Create: `job_pipeline/stages/agents/score.py`
- Delete: `job_pipeline/stages/agents.py`
- Modify: `README.md` (the "Pluggable sources, stages, and seeders" section — see Step 8)
- Test: none (existing `tests/test_agent_stages.py` is the gate and must not change)

**Interfaces:**
- Consumes: `_fill` moves to `job_pipeline/stages/agents/common.py`; the package pattern mirrors Task 1's `rules/` package exactly.
- Produces: package `job_pipeline.stages.agents` exporting exactly `ExtractStage`, `SkillGapStage`, `ScoreStage`, `ExtractReply`, `SkillGapReply`, `ScoreReply`, `EXTRACT_PROMPT`, `SKILL_GAP_PROMPT`, `SCORE_PROMPT`, `_fill`.

- [ ] **Step 1: Create `job_pipeline/stages/agents/common.py`**

```python
"""Helpers shared by the agent stages."""
from __future__ import annotations


def _fill(template: str, **values: object) -> str:
    """Brace-safe template fill: values may contain literal { } freely."""
    out = template
    for key, value in values.items():
        out = out.replace("{" + key + "}", str(value))
    return out
```

- [ ] **Step 2: Create `job_pipeline/stages/agents/extract.py`**

```python
"""Extract stage: normalize a raw listing into structured fields.

The prompt is a frozen module constant for cache stability.
"""
from __future__ import annotations

from pydantic import BaseModel

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.agents.common import _fill


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


EXTRACT_PROMPT = """Extract structured fields from this job listing. Reply with ONLY a JSON object:
{"title": str, "company": str, "location": str, "comp_text": str,
 "comp_min": int|null, "comp_max": int|null, "comp_currency": str|null,
 "comp_period": "annual"|"hourly"|null, "requirements": [str], "description": str,
 "employer_address": str, "employer_phone": str, "employer_email": str}
comp_min/comp_max are numbers only (e.g. "$150k" -> 150000). Use "" / null / [] when absent.
description is a 2-3 sentence summary.

LISTING:
{raw_text}"""


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
            _fill(EXTRACT_PROMPT, raw_text=job.raw_text), self.model, ExtractReply
        )
        for field_name, value in reply.model_dump().items():
            setattr(job, field_name, value)
        job.add_trace("extract", "extracted")
        return job
```

- [ ] **Step 3: Create `job_pipeline/stages/agents/skill_gap.py`**

```python
"""Skill-gap stage: compare resume/skills to job requirements.

The prompt is a frozen module constant for cache stability.
"""
from __future__ import annotations

from pydantic import BaseModel

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.agents.common import _fill


class SkillGapReply(BaseModel):
    have: list[str] = []
    missing: list[str] = []
    partial: list[str] = []


SKILL_GAP_PROMPT = """Compare this candidate against the job requirements. Reply with ONLY a JSON object:
{"have": [str], "missing": [str], "partial": [str]}

CANDIDATE PROFILE:
{profile_body}

JOB REQUIREMENTS:
{requirements}

JOB DESCRIPTION:
{description}"""


@register_stage("skill_gap")
class SkillGapStage:
    spec = StageSpec("skill_gap", "compare resume/skills to job requirements",
                     requires=["requirements", "description"], produces=["skill_gap"],
                     kind="agent", cost_tier="mid")

    def __init__(self, runner: AgentRunner, model: str, profile: Profile) -> None:
        self.runner, self.model, self.profile = runner, model, profile

    def run(self, job: Job) -> Job:
        reply = self.runner.run(
            _fill(
                SKILL_GAP_PROMPT,
                profile_body=self.profile.body,
                requirements=job.requirements,
                description=job.description,
            ),
            self.model, SkillGapReply,
        )
        job.skill_gap = reply.model_dump()
        job.add_trace("skill_gap", "analyzed")
        return job
```

- [ ] **Step 4: Create `job_pipeline/stages/agents/score.py`**

```python
"""Score stage: final fit judgment with rationale.

The prompt is a frozen module constant for cache stability.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.runner import AgentRunner
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.agents.common import _fill


class ScoreReply(BaseModel):
    score: float = Field(ge=0, le=100)
    rationale: str


SCORE_PROMPT = """Score this job 0-100 for fit against the candidate's profile and preferences.
Reply with ONLY a JSON object: {"score": number, "rationale": str}
The rationale should be 2-4 sentences naming the decisive factors.

CANDIDATE PROFILE AND PREFERENCES:
{profile_body}

JOB: {title} at {company} ({location}) — {comp_text}
DESCRIPTION: {description}
SKILL GAP: {skill_gap}"""


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
            _fill(
                SCORE_PROMPT,
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

- [ ] **Step 5: Create `job_pipeline/stages/agents/__init__.py`**

```python
"""The three agent stages. Prompts are frozen module constants for cache stability."""
from job_pipeline.stages.agents.common import _fill
from job_pipeline.stages.agents.extract import EXTRACT_PROMPT, ExtractReply, ExtractStage
from job_pipeline.stages.agents.score import SCORE_PROMPT, ScoreReply, ScoreStage
from job_pipeline.stages.agents.skill_gap import (
    SKILL_GAP_PROMPT,
    SkillGapReply,
    SkillGapStage,
)

__all__ = [
    "_fill",
    "EXTRACT_PROMPT",
    "SKILL_GAP_PROMPT",
    "SCORE_PROMPT",
    "ExtractReply",
    "SkillGapReply",
    "ScoreReply",
    "ExtractStage",
    "SkillGapStage",
    "ScoreStage",
]
```

- [ ] **Step 6: Delete the old flat module**

```bash
git rm job_pipeline/stages/agents.py
find . -name __pycache__ -type d -prune -exec rm -rf {} +
```

- [ ] **Step 7: Run the full suite and verify zero test edits**

Run: `.venv/bin/pytest -q`
Expected: `71 passed, 1 deselected`

Run: `git status --porcelain tests/`
Expected: no output

- [ ] **Step 8: Update the README extending section**

In `README.md`, find this line in "### 2. Pluggable sources, stages, and seeders via the registry":

```markdown
Register a new adapter by name; core code is unchanged.
```

Replace it with:

```markdown
Register a new adapter by name; core code is unchanged.

Each stage lives in its own module — deterministic filters under
`job_pipeline/stages/rules/`, agent stages under `job_pipeline/stages/agents/`.
To write your own, copy the closest existing one as a template
(`stages/rules/location.py` for a filter, `stages/agents/skill_gap.py` for an
agent stage), register it with `@register_stage("your_name")`, and add the name
to `stages:` in `pipeline.yaml`.
```

- [ ] **Step 9: Commit**

```bash
git add job_pipeline/stages/agents/ README.md
git commit -m "refactor: split stages/agents.py into one-module-per-stage package"
```

(The `git rm` from Step 6 is already staged.)

---

## Verification (whole plan)

- `.venv/bin/pytest -q` → `71 passed, 1 deselected`
- `git diff <base>..HEAD --stat -- tests/` → empty
- `python -c "from job_pipeline.stages.rules import make_fuzzy_key; from job_pipeline.stages.agents import ExtractStage, _fill, EXTRACT_PROMPT; print('ok')"` (run with `.venv/bin/python`) → `ok`
