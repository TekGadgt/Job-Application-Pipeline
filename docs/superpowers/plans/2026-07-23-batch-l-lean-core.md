# Batch L — Lean Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the location and salary gates, demote fuzzy dedup to record-only, and remove dead profile config — the default pipeline becomes `[dedup, hard_filter, extract, dedup_fuzzy, skill_gap, score, publish]`.

**Architecture:** Spec: `docs/superpowers/specs/2026-07-23-lean-core-design.md`. Pure deletion/demotion — no new modules. Stages self-register via `@register_stage` on import (aggregated in `job_pipeline/stages/rules/__init__.py`); deleting a module removes its registration, and `build_stages` in `core/pipeline.py` holds a per-stage deps dict that must drop the deleted entries. Philosophy: filter almost nothing deterministically; the fit score carries judgment; the *data* (location string, fuzzy key) survives — only the *gating* goes.

**Tech Stack:** Python 3.12, pydantic v2, pytest. No network, no model tokens in tests (`MockRunner`).

## Global Constraints

- **Never touch:** `hard_filter` (explicit keeper), `dedup` (URL dedup, the only hard reject besides hard_filter), `score_floor` (optional opt-in stage — stays registered and tested).
- Tests must not use network or real model calls; agent stages are exercised via `MockRunner`.
- Pydantic v2 `BaseModel` default is `extra='ignore'`: unknown yaml keys load silently. Removed config fields must be verified *inert*, not erroring.
- Existing tests for deleted behavior are **removed, not skipped**.
- Commit after every task; messages follow repo style (`feat:`/`refactor:`/`docs:` prefixes, imperative).
- Run tests with `pytest` from the repo root.

---

### Task 1: `dedup_fuzzy` becomes record-only

**Files:**
- Modify: `job_pipeline/stages/rules/dedup_fuzzy.py`
- Test: `tests/test_rule_stages.py:60-94`, `tests/test_pipeline_e2e.py:77-103`

**Interfaces:**
- Consumes: `SeenIndex.has_fuzzy(key)`, `make_fuzzy_key`/`legacy_fuzzy_key` from `stages/rules/common.py` (unchanged).
- Produces: `FuzzyDedupStage.run` never rejects; sets `job.fuzzy_key` exactly as before; traces `possible duplicate: <key>` on a hit. `spec.produces == ["fuzzy_key"]`. Later tasks rely on the stage never setting `job.rejected`.

- [ ] **Step 1: Rewrite the three affected stage tests to the new record-only contract**

In `tests/test_rule_stages.py`, replace `test_fuzzy_dedup_rejects_cross_source_duplicate` (lines 60-66) and `test_fuzzy_dedup_legacy_row_blocks_all_locations` (lines 78-87) with:

```python
def test_fuzzy_dedup_flags_cross_source_duplicate_but_passes(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("otherhash", "acme|engineer|remote")
    j = make_job(company="Acme", title="Engineer", location="Remote")
    out = FuzzyDedupStage(idx).run(j)
    assert not out.rejected
    assert out.fuzzy_key == "acme|engineer|remote"
    assert any("possible duplicate: acme|engineer|remote" in verdict
               for _, verdict, _ in out.trace)


def test_fuzzy_dedup_legacy_row_flags_all_locations(tmp_path):
    # Rows written before location-aware keys hold the 2-part form and
    # still flag the role everywhere — but no longer reject it.
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("oldhash", "acme|engineer")
    out = FuzzyDedupStage(idx).run(
        make_job(company="Acme", title="Engineer", location="Berlin"))
    assert not out.rejected
    # the trace names the key that actually matched, not the 3-part probe
    assert any("possible duplicate: acme|engineer (legacy pre-location match)" in verdict
               for _, verdict, _ in out.trace)
```

Leave `test_fuzzy_dedup_passes_same_role_different_location` and `test_fuzzy_dedup_no_key_when_company_and_title_empty` untouched — they already assert the pass-through behavior.

- [ ] **Step 2: Rewrite the e2e repost test — a fuzzy-flagged repost now publishes**

In `tests/test_pipeline_e2e.py`, replace `test_same_role_different_location_publishes_then_repost_rejects` (lines 77-103) with:

```python
def test_same_role_repost_publishes_flagged_not_rejected(tmp_path):
    cfg = make_cfg(tmp_path)
    prof = Profile(salary_floor=100000, blocklist=["web3"], body="Python dev",
                   locations=LocationRules(remote=True, allowed_metros=["New York"]))
    db = tmp_path / "seen.sqlite"

    def extract(loc):
        return {"title": "Forward Deployed Engineer", "company": "LiveKit",
                "location": loc, "comp_text": "$150k", "comp_min": 150000,
                "comp_max": 150000, "comp_currency": "USD", "comp_period": "annual",
                "requirements": ["python"], "description": "d"}

    gap = {"have": ["python"], "missing": [], "partial": []}
    score = {"score": 90.0, "rationale": "great"}

    # Run 1: same role in two locations -> both publish
    run1 = FakeSource([job("https://x.com/a", "listing a"), job("https://x.com/b", "listing b")])
    s1 = run_pipeline(cfg, prof, MockRunner(
        [extract("Remote"), gap, score, extract("New York, NY"), gap, score]),
        sources=[run1], db_path=db)
    assert s1.published == 2 and s1.rejected == 0

    # Run 2: repost of the Remote role under a third URL -> publishes anyway,
    # fuzzy dedup only records the possible-duplicate signal (URL is the only hard dedup)
    run2 = FakeSource([job("https://x.com/c", "listing c")])
    s2 = run_pipeline(cfg, prof, MockRunner([extract("Remote"), gap, score]),
                      sources=[run2], db_path=db)
    assert s2.published == 1 and s2.rejected == 0
```

(Note run 2's `MockRunner` now needs all three replies — the job no longer stops at `dedup_fuzzy`.)

- [ ] **Step 3: Run the changed tests to verify they fail**

Run: `pytest tests/test_rule_stages.py -k fuzzy -v` and `pytest tests/test_pipeline_e2e.py::test_same_role_repost_publishes_flagged_not_rejected -v`
Expected: the two rewritten stage tests and the e2e test FAIL (stage still rejects); the two untouched fuzzy tests PASS.

- [ ] **Step 4: Rewrite the stage**

Replace the body of `job_pipeline/stages/rules/dedup_fuzzy.py` with:

```python
"""Record cross-source duplicate signal by normalized company+title+location.

Record-only since the 2026-07-23 lean re-cut: URL dedup is the only hard
dedup; a fuzzy hit traces `possible duplicate` and the job continues.
"""
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.rules.common import legacy_fuzzy_key, make_fuzzy_key
from job_pipeline.store.seen_index import SeenIndex


@register_stage("dedup_fuzzy")
class FuzzyDedupStage:
    spec = StageSpec("dedup_fuzzy", "record company+title+location key; flag possible duplicates",
                     requires=["company", "title", "location"],
                     produces=["fuzzy_key"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, seen_index: SeenIndex) -> None:
        self.seen = seen_index

    def run(self, job: Job) -> Job:
        legacy = legacy_fuzzy_key(job.company, job.title)
        if legacy == "|":                     # company and title both empty: no key
            job.fuzzy_key = ""
            job.add_trace("dedup_fuzzy", "no key (empty company+title)")
            return job
        job.fuzzy_key = make_fuzzy_key(job.company, job.title, job.location)
        if self.seen.has_fuzzy(job.fuzzy_key):
            job.add_trace("dedup_fuzzy", f"possible duplicate: {job.fuzzy_key}")
        elif self.seen.has_fuzzy(legacy):
            # name the key that actually matched — legacy rows flag all locations
            job.add_trace("dedup_fuzzy", f"possible duplicate: {legacy} (legacy pre-location match)")
        else:
            job.add_trace("dedup_fuzzy", "passed")
        return job
```

- [ ] **Step 5: Run the full suite to verify green**

Run: `pytest`
Expected: all tests PASS.

- [ ] **Step 6: Commit**

```bash
git add job_pipeline/stages/rules/dedup_fuzzy.py tests/test_rule_stages.py tests/test_pipeline_e2e.py
git commit -m "feat: dedup_fuzzy record-only — URL is the only hard dedup"
```

---

### Task 2: Delete the location and salary gates

**Files:**
- Delete: `job_pipeline/stages/rules/location.py`, `job_pipeline/stages/rules/salary.py`
- Modify: `job_pipeline/stages/rules/__init__.py`, `job_pipeline/stages/rules/common.py`, `job_pipeline/core/pipeline.py:39-50`, `job_pipeline/core/job.py:33-35`
- Test: `tests/test_rule_stages.py`, `tests/test_pipeline_e2e.py`, `tests/test_job.py:31`

**Interfaces:**
- Consumes: Task 1's record-only `dedup_fuzzy` (the e2e stage lists shrink around it).
- Produces: registry no longer resolves `"location"`/`"salary"`; `Job` loses `location_ok`/`salary_ok`; `stages/rules/common.py` exports only `_norm`, `make_fuzzy_key`, `legacy_fuzzy_key` (no `HOURS_PER_YEAR`); `stages/rules/__init__.py` exports `legacy_fuzzy_key, make_fuzzy_key, DedupStage, FuzzyDedupStage, HardFilterStage, ScoreFloorStage`. Task 3 relies on `Profile.locations`/`salary_floor` still existing until then.

- [ ] **Step 1: Update tests to the lean stage list and add the registry-removal test**

In `tests/test_rule_stages.py`:
- Fix the imports (lines 3-8) to:

```python
from datetime import datetime, UTC
from job_pipeline.core.job import Job
from job_pipeline.config import Profile
from job_pipeline.store.seen_index import SeenIndex
from job_pipeline.stages.rules import (
    DedupStage, HardFilterStage, FuzzyDedupStage,
    make_fuzzy_key,
)
```

- Delete the entire `# --- location ---` section (3 tests, lines 97-112) and `# --- salary ---` section (5 tests, lines 115-142).
- Append a registry test at the end of the file:

```python
# --- lean re-cut: gates are gone ---
def test_location_and_salary_stages_are_gone():
    import pytest
    from job_pipeline.core.registry import get_stage
    for name in ("location", "salary"):
        with pytest.raises(KeyError):
            get_stage(name)
```

(If `get_stage` raises something other than `KeyError` for unknown names, check `job_pipeline/core/registry.py` and assert that exception instead.)

In `tests/test_pipeline_e2e.py`:
- `make_cfg` (line 21-22): stages become
  `["dedup", "hard_filter", "extract", "dedup_fuzzy", "skill_gap", "score", "publish"]`
- `test_score_floor_rejects_low_scoring_job_terminally` (line 108-109): stages become
  `["dedup", "hard_filter", "extract", "dedup_fuzzy", "skill_gap", "score", "score_floor", "publish"]`

In `tests/test_job.py` line 31: change
`assert j.comp_min is None and j.salary_ok is None` → `assert j.comp_min is None and j.score is None`

- [ ] **Step 2: Run the suite to verify the expected failures**

Run: `pytest tests/test_rule_stages.py tests/test_pipeline_e2e.py tests/test_job.py -v`
Expected: `test_location_and_salary_stages_are_gone` FAILS (stages still registered); everything else PASSES (the lean stage lists already work — the gates were just list entries).

- [ ] **Step 3: Delete the gate modules and scrub the references**

```bash
git rm job_pipeline/stages/rules/location.py job_pipeline/stages/rules/salary.py
```

`job_pipeline/stages/rules/__init__.py` becomes:

```python
"""The free deterministic filter stages. No model tokens are spent here."""
from job_pipeline.stages.rules.common import legacy_fuzzy_key, make_fuzzy_key
from job_pipeline.stages.rules.dedup import DedupStage
from job_pipeline.stages.rules.dedup_fuzzy import FuzzyDedupStage
from job_pipeline.stages.rules.hard_filter import HardFilterStage
from job_pipeline.stages.rules.score_floor import ScoreFloorStage

__all__ = [
    "legacy_fuzzy_key",
    "make_fuzzy_key",
    "DedupStage",
    "FuzzyDedupStage",
    "HardFilterStage",
    "ScoreFloorStage",
]
```

`job_pipeline/stages/rules/common.py`: delete the `HOURS_PER_YEAR = 2080` line (its only consumer was the salary stage).

`job_pipeline/core/pipeline.py` `build_stages` deps dict: delete the two lines
`"location": lambda c: c(profile),` and `"salary": lambda c: c(profile),`.

`job_pipeline/core/job.py`: delete the `# after rule stages` comment block and both fields `location_ok: bool | None = None` and `salary_ok: bool | None = None`.

- [ ] **Step 4: Run the full suite to verify green**

Run: `pytest`
Expected: all tests PASS, including `test_location_and_salary_stages_are_gone`.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat: delete location and salary gates (lean core)"
```

---

### Task 3: Profile and config cleanup

**Files:**
- Modify: `job_pipeline/config.py:12-31`
- Test: `tests/test_config.py`, `tests/test_pipeline_e2e.py`, `tests/test_agent_stages.py:34`

**Interfaces:**
- Consumes: gate-free codebase from Task 2 (nothing reads the removed fields anymore).
- Produces: `Profile` fields are exactly `score_floor: int | None`, `blocklist: list[str]`, `body: str`; `LocationRules` class deleted; `OutputConfig` field is exactly `vault: Path`. Stale yaml keys load inert (pydantic `extra='ignore'`). Task 4's example configs match this shape.

- [ ] **Step 1: Write the inert-key tests and update fixtures**

In `tests/test_config.py`:
- Leave the `PROFILE` and `PIPELINE` fixture strings **unchanged** — their dead keys (`salary_floor`, `locations`, `must_have_skills`, `nice_to_have`, `salary_not_listed`, `keep_rejects: true`) become the inert-key coverage.
- Replace `test_load_profile_parses_frontmatter_and_body` with:

```python
def test_load_profile_parses_frontmatter_and_body(tmp_path):
    p = tmp_path / "profile.md"
    p.write_text(PROFILE)
    prof = load_profile(p)
    assert "web3" in prof.blocklist
    assert "I write Python." in prof.body
    # keys removed in the 2026-07-23 lean re-cut load inert, not as errors
    for dead in ("salary_floor", "locations", "must_have_skills",
                 "nice_to_have", "salary_not_listed"):
        assert not hasattr(prof, dead)
```

- Delete `test_profile_rejects_bad_salary_not_listed` (lines 38-42) — the field no longer exists, so nothing validates it.
- In `test_load_pipeline_config`, add the assertion:

```python
    assert not hasattr(cfg.output, "keep_rejects")   # retired dead config
```

- In `tests/test_pipeline_e2e.py`: drop `LocationRules` from the line-3 import (`from job_pipeline.config import Profile, PipelineConfig, OutputConfig, Limits`); `make_profile` becomes `return Profile(blocklist=["web3"], body="Python dev")`; in `test_same_role_repost_publishes_flagged_not_rejected` the inline profile becomes `Profile(blocklist=["web3"], body="Python dev")`.
- In `tests/test_agent_stages.py` line 34: `Profile(must_have_skills=["python"], body="## Resume\nPython dev")` → `Profile(body="## Resume\nPython dev")`.

- [ ] **Step 2: Run the config tests to verify the expected failures**

Run: `pytest tests/test_config.py -v`
Expected: `test_load_profile_parses_frontmatter_and_body` FAILS (`hasattr(prof, "salary_floor")` is still True) and the `keep_rejects` assertion FAILS. Others PASS.

- [ ] **Step 3: Trim the config models**

In `job_pipeline/config.py`: delete the `LocationRules` class entirely; delete the now-unused `Literal` import; `Profile` and `OutputConfig` become:

```python
class Profile(BaseModel):
    score_floor: int | None = None
    blocklist: list[str] = []
    body: str = ""                      # prose: resume + fuzzy preferences


class OutputConfig(BaseModel):
    vault: Path
```

- [ ] **Step 4: Run the full suite to verify green**

Run: `pytest`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add job_pipeline/config.py tests/test_config.py tests/test_pipeline_e2e.py tests/test_agent_stages.py
git commit -m "refactor: trim Profile/OutputConfig to lean-core fields; stale keys load inert"
```

---

### Task 4: Config files, README, and final verification

**Files:**
- Modify: `config/pipeline.yaml`, `config/pipeline.example.yaml`, `config/profile.md`, `config/profile.example.md`, `README.md`

**Interfaces:**
- Consumes: everything above; this task is docs/config only — no Python changes.
- Produces: shipped configs match the lean default `[dedup, hard_filter, extract, dedup_fuzzy, skill_gap, score, publish]`.

- [ ] **Step 1: Update both pipeline yamls**

In `config/pipeline.yaml` **and** `config/pipeline.example.yaml`:
- `stages:` line becomes:

```yaml
stages: [dedup, hard_filter, extract, dedup_fuzzy, skill_gap, score, publish]
```

- `output:` line drops `keep_rejects` — becomes (keep each file's own vault path):

```yaml
output: {vault: ~/Documents/TekGadgt-Remote/job_application_pipeline}   # pipeline.yaml
output: {vault: ~/vault/jobs}                                           # pipeline.example.yaml
```

- [ ] **Step 2: Trim both profile frontmatters; move preferences into prose**

`config/profile.example.md` frontmatter becomes:

```yaml
---
# score_floor: 60        # optional: reject scored jobs below this (terminal — see README)
blocklist: [crypto, web3, blockchain, defi]
---
```

(Also update the example's prose hint under "What I'm looking for" to mention location/salary preferences belong here now, e.g. append: `Location and salary preferences go here too — the score agent weighs them; nothing filters on them.`)

`config/profile.md` frontmatter becomes exactly:

```yaml
---
blocklist: [crypto, web3, blockchain, surveillance]
---
```

and append to its `## What I'm looking for` section:

```markdown
Location: open to fully remote roles, and open to relocating for the right on-site/hybrid role — do not penalize location.
Compensation: generally targeting $100k+ base (or equivalent in other currencies); treat lower or unlisted comp as a fit consideration, not a dealbreaker.
```

- [ ] **Step 3: Update the README**

In `README.md`:
- Pipeline overview list: rewrite item 5 (line ~21) to:

```markdown
5. **Post-extract dedup** (Python) — fuzzy key `normalize(company) + normalize(title) + normalize(location)` records the same role seen via different URLs. Record-only since the 2026-07-23 lean re-cut: a hit traces `possible duplicate` and the job continues — a duplicate note costs seconds of triage, a falsely-deduped posting is an application never made.
```

- Delete item 6 (**Location**, line ~22) and the salary/comp-floor gate item if one follows it; renumber the remaining items so the list stays contiguous.
- Line ~48: `$EDITOR config/profile.md       # paste your résumé, set salary_floor, blocklist, etc.` → `$EDITOR config/profile.md       # paste your résumé, set blocklist, etc.`
- Line ~90 stages example → `stages: [dedup, hard_filter, extract, dedup_fuzzy, skill_gap, score, publish]`
- Line ~115 custom-stage pointer: replace the `job_pipeline/stages/rules/location.py` example with `job_pipeline/stages/rules/score_floor.py`.
- Scan the README for any other `location`/`salary`/`keep_rejects` gate references (`grep -n "location\|salary\|keep_rejects" README.md`) and update them to match lean-core behavior. Do not touch the HN extract-hint example block (~line 140) — its "salary often absent" text describes listings, not our config.

- [ ] **Step 4: Full verification sweep**

```bash
pytest
grep -rn "location_ok\|salary_ok\|LocationStage\|SalaryStage\|HOURS_PER_YEAR\|LocationRules\|keep_rejects\|salary_floor\|salary_not_listed\|must_have\|nice_to_have" job_pipeline/ tests/ config/ README.md
```

Expected: `pytest` all PASS; grep returns **no hits** (docs/superpowers/ specs and plans are intentionally excluded from the grep paths — history stays intact).

- [ ] **Step 5: Commit**

```bash
git add config/ README.md
git commit -m "docs: lean-core config and README — gates removed, fuzzy dedup record-only"
```

---

## Post-plan notes for the executor

- Branch: `feat/batch-l-lean-core` off `main`; Ryan pushes/PRs/merges himself — do not push.
- If `.superpowers/sdd/progress.md` exists, append one line per completed task (Batch A pattern).
- The live vault/seen-index at `~/Documents/TekGadgt-Remote/job_application_pipeline/` is real user data — nothing in this plan touches it; don't run the CLI against it.
