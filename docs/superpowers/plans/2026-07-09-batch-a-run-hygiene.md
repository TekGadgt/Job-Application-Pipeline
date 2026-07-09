# Batch A — Run Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three things biting daily runs: location-collapsing fuzzy dedup (specs: `2026-07-09-location-aware-fuzzy-dedup-design.md`), unfiltered low-score notes (`2026-07-09-score-floor-design.md`), and no way to deliberately re-run a seen URL (`2026-07-03-reprocess-flag-design.md`).

**Architecture:** Fuzzy keys become 3-part `company|title|location` with a legacy 2-part compatibility check (old rows keep blocking all locations; no migration). A new free rule stage `score_floor` rejects below-floor jobs between `score` and `publish`. `SeenIndex.unmark` + a CLI `--reprocess` flag clear seen rows for given `--url`s before a run.

**Tech Stack:** Python ≥3.11, pytest, sqlite3. No new dependencies.

## Global Constraints

- Tests spend **no** model tokens and make **no** network calls (MockRunner/fakes); no real personal data in fixtures.
- Legacy compatibility (binding): fuzzy rows written before this change hold 2-part keys (`company|title`) and **must keep blocking the role in all locations**. New rows are 3-part. No schema change; `SeenIndex.has_fuzzy` signature unchanged.
- "No key" rule: a fuzzy key is never marked and never matched when **normalized company AND title are both empty** (replaces the old literal `"|"` guard).
- `score_floor` boundary is **inclusive-keep**: `score == floor` passes. `floor is None` and `score is None` both pass with a trace.
- `--reprocess` without `--url` exits non-zero with message `--reprocess requires --url (no blanket un-marking)`.
- Baseline before Task 1: `.venv/bin/pytest -q` → `78 passed, 1 deselected`.
- Each task's expected test count is stated in its final full-suite step; existing tests may only change where a step explicitly shows the change.

---

### Task 1: Location-aware fuzzy keys + FuzzyDedupStage

**Files:**
- Modify: `job_pipeline/stages/rules/common.py` (whole file, shown below)
- Modify: `job_pipeline/stages/rules/dedup_fuzzy.py` (imports + `run`)
- Modify: `job_pipeline/stages/rules/__init__.py` (export `legacy_fuzzy_key`)
- Modify: `tests/test_rule_stages.py` (2 existing tests updated, 4 added)
- Modify: `tests/test_pipeline_e2e.py` (1 added)
- Modify: `README.md` (dedup list item)

**Interfaces:**
- Consumes: existing `SeenIndex.has_fuzzy(key) -> bool`, `Job.location`.
- Produces: `make_fuzzy_key(company: str, title: str, location: str = "") -> str` (3-part, trailing part may be empty → `"acme|engineer|"`); `legacy_fuzzy_key(company: str, title: str) -> str` (2-part, pre-change format). Task 2's seeder imports **both** from `job_pipeline.stages.rules`.

- [ ] **Step 1: Confirm the green baseline**

Run: `.venv/bin/pytest -q`
Expected: `78 passed, 1 deselected`

- [ ] **Step 2: Update the two affected existing tests and add the new failing tests**

In `tests/test_rule_stages.py`, replace `test_make_fuzzy_key_normalizes` (line 50-51) and `test_fuzzy_dedup_rejects_cross_source_duplicate` (lines 54-60) with:

```python
def test_make_fuzzy_key_normalizes():
    assert make_fuzzy_key("Acme, Inc.", "Sr. Engineer") == "acmeinc|srengineer|"
    assert make_fuzzy_key("Acme, Inc.", "Sr. Engineer", "Remote (US)") == "acmeinc|srengineer|remoteus"


def test_legacy_fuzzy_key_is_two_part():
    from job_pipeline.stages.rules import legacy_fuzzy_key
    assert legacy_fuzzy_key("Acme, Inc.", "Sr. Engineer") == "acmeinc|srengineer"


def test_fuzzy_dedup_rejects_cross_source_duplicate(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("otherhash", "acme|engineer|remote")
    j = make_job(company="Acme", title="Engineer", location="Remote")
    out = FuzzyDedupStage(idx).run(j)
    assert out.rejected and out.reject_stage == "dedup_fuzzy"
    assert j.fuzzy_key == "acme|engineer|remote"
```

Then append these new tests at the end of the `# --- fuzzy key + fuzzy dedup ---` section:

```python
def test_fuzzy_dedup_passes_same_role_different_location(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("otherhash", "acme|engineer|remote")
    out = FuzzyDedupStage(idx).run(
        make_job(company="Acme", title="Engineer", location="New York, NY"))
    assert not out.rejected
    assert out.fuzzy_key == "acme|engineer|newyorkny"


def test_fuzzy_dedup_legacy_row_blocks_all_locations(tmp_path):
    # Rows written before location-aware keys hold the 2-part form and
    # keep blocking the role everywhere.
    idx = SeenIndex(tmp_path / "s.sqlite")
    idx.mark("oldhash", "acme|engineer")
    out = FuzzyDedupStage(idx).run(
        make_job(company="Acme", title="Engineer", location="Berlin"))
    assert out.rejected and out.reject_stage == "dedup_fuzzy"


def test_fuzzy_dedup_no_key_when_company_and_title_empty(tmp_path):
    idx = SeenIndex(tmp_path / "s.sqlite")
    out = FuzzyDedupStage(idx).run(make_job(company="", title="", location="Remote"))
    assert not out.rejected
    assert out.fuzzy_key == ""
```

- [ ] **Step 3: Run to verify failures**

Run: `.venv/bin/pytest tests/test_rule_stages.py -v`
Expected: FAIL — `test_make_fuzzy_key_normalizes` gets `"acmeinc|srengineer"` (no third part), `test_legacy_fuzzy_key_is_two_part` ImportError, the location tests fail on missing behavior.

- [ ] **Step 4: Rewrite `job_pipeline/stages/rules/common.py`**

Replace the whole file with:

```python
"""Helpers shared by more than one rule stage."""
from __future__ import annotations

import re

HOURS_PER_YEAR = 2080


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def make_fuzzy_key(company: str, title: str, location: str = "") -> str:
    """Location-aware dedup key. The same role listed for different
    locations is a different job; see the 2026-07-09 dedup spec."""
    return f"{_norm(company)}|{_norm(title)}|{_norm(location)}"


def legacy_fuzzy_key(company: str, title: str) -> str:
    """Pre-location key format. Seen-index rows written before 2026-07
    hold this form and block the role in ALL locations."""
    return f"{_norm(company)}|{_norm(title)}"
```

- [ ] **Step 5: Update `job_pipeline/stages/rules/dedup_fuzzy.py`**

Change the import line and the `run` method (StageSpec `requires` gains `"location"`):

```python
"""Drop cross-source duplicates by normalized company+title+location."""
from __future__ import annotations

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec
from job_pipeline.stages.rules.common import legacy_fuzzy_key, make_fuzzy_key
from job_pipeline.store.seen_index import SeenIndex


@register_stage("dedup_fuzzy")
class FuzzyDedupStage:
    spec = StageSpec("dedup_fuzzy", "drop cross-source duplicates by company+title+location",
                     requires=["company", "title", "location"],
                     produces=["fuzzy_key", "rejected"],
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
        if self.seen.has_fuzzy(job.fuzzy_key) or self.seen.has_fuzzy(legacy):
            job.mark_rejected("dedup_fuzzy", f"duplicate role: {job.fuzzy_key}")
        else:
            job.add_trace("dedup_fuzzy", "passed")
        return job
```

- [ ] **Step 6: Export `legacy_fuzzy_key` from the package**

In `job_pipeline/stages/rules/__init__.py`: change the `common` import line to

```python
from job_pipeline.stages.rules.common import HOURS_PER_YEAR, legacy_fuzzy_key, make_fuzzy_key
```

and add `"legacy_fuzzy_key",` to `__all__` (after `"make_fuzzy_key",`).

- [ ] **Step 7: Run the rule-stage tests**

Run: `.venv/bin/pytest tests/test_rule_stages.py -v`
Expected: all PASS.

- [ ] **Step 8: Add the two-run repost e2e test**

Append to `tests/test_pipeline_e2e.py`:

```python
def test_same_role_different_location_publishes_then_repost_rejects(tmp_path):
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

    # Run 2: repost of the Remote role under a third URL -> fuzzy dedup rejects
    run2 = FakeSource([job("https://x.com/c", "listing c")])
    s2 = run_pipeline(cfg, prof, MockRunner([extract("Remote")]),
                      sources=[run2], db_path=db)
    assert s2.published == 0 and s2.rejected == 1
```

- [ ] **Step 9: Update the README dedup item**

In `README.md`, replace list item 5:

```markdown
5. **Post-extract dedup** (Python) — fuzzy key `normalize(company) + normalize(title)` catches the same role via different URLs.
```

with:

```markdown
5. **Post-extract dedup** (Python) — fuzzy key `normalize(company) + normalize(title) + normalize(location)` catches the same role via different URLs, while the same role listed separately per location is treated as distinct. Location is free text, so a repost with a reworded location can slip through as a duplicate note — deliberately: a duplicate note costs seconds of triage, a falsely-deduped posting is an application never made.
```

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `83 passed, 1 deselected` (78 − 0 removed + 4 new rule tests + 1 e2e; two tests rewritten in place).

- [ ] **Step 11: Commit**

```bash
git add job_pipeline/stages/rules/ tests/test_rule_stages.py tests/test_pipeline_e2e.py README.md
git commit -m "feat: location-aware fuzzy dedup keys with legacy 2-part compatibility"
```

---

### Task 2: Seeder `location_field`

**Files:**
- Modify: `job_pipeline/seeders/existing_vault.py`
- Modify: `tests/test_seeder.py` (2 added)
- Modify: `docs/superpowers/specs/2026-07-03-vault-import-design.md` (one line — keeps that spec truthful, per the dedup spec's coordination section)

**Interfaces:**
- Consumes: `make_fuzzy_key(company, title, location)` and `legacy_fuzzy_key(company, title)` from `job_pipeline.stages.rules` (Task 1).
- Produces: `ExistingVaultSeeder(path, url_field="source_url", company_field="company", title_field="position", location_field="")` — `location_field` unset or note lacks the field → legacy 2-part key (block-everywhere, old-tracker semantics); set and present → 3-part key.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_seeder.py`:

```python
def test_seed_without_location_field_writes_legacy_key(tmp_path):
    (tmp_path / "note.md").write_text(NOTE)
    idx = SeenIndex(tmp_path / "seen.sqlite")
    ExistingVaultSeeder(path=tmp_path).seed(idx)
    assert idx.has_fuzzy("acmecorp|seniorengineer")        # 2-part legacy form


def test_seed_with_location_field_writes_three_part_key(tmp_path):
    (tmp_path / "n.md").write_text(
        '---\ncompany: "Acme Corp"\nposition: "Senior Engineer"\n'
        'location: "Remote (US)"\nsource_url: "https://x.com/jobs/9"\n---\nx'
    )
    idx = SeenIndex(tmp_path / "seen.sqlite")
    ExistingVaultSeeder(path=tmp_path, location_field="location").seed(idx)
    assert idx.has_fuzzy("acmecorp|seniorengineer|remoteus")
    assert not idx.has_fuzzy("acmecorp|seniorengineer")    # not the legacy form
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_seeder.py -v`
Expected: `test_seed_with_location_field_writes_three_part_key` FAILS with `TypeError: __init__() got an unexpected keyword argument 'location_field'`. (The legacy-key test may already pass — Task 1's `legacy_fuzzy_key` isn't wired into the seeder yet, but the seeder's current 2-arg `make_fuzzy_key` call now produces a 3-part `…|` key, so it FAILS too. Both failing is the expected state.)

- [ ] **Step 3: Update the seeder**

In `job_pipeline/seeders/existing_vault.py`: change the rules import (line 10), `__init__` (lines 16-21), and the fuzzy computation (lines 38-41):

```python
from job_pipeline.stages.rules import legacy_fuzzy_key, make_fuzzy_key
```

```python
    def __init__(self, path: Path | str, url_field: str = "source_url",
                 company_field: str = "company", title_field: str = "position",
                 location_field: str = "") -> None:
        self.path = Path(path).expanduser()
        self.url_field = url_field
        self.company_field = company_field
        self.title_field = title_field
        self.location_field = location_field
```

```python
            company = str(data.get(self.company_field, ""))
            title = str(data.get(self.title_field, ""))
            loc = str(data.get(self.location_field, "")) if self.location_field else ""
            if legacy_fuzzy_key(company, title) == "|":
                fuzzy = ""                    # no key: company and title both empty
            elif loc:
                fuzzy = make_fuzzy_key(company, title, loc)
            else:
                fuzzy = legacy_fuzzy_key(company, title)   # block-everywhere semantics
            seen_index.mark(url_hash, fuzzy)
```

(The old `fuzzy if fuzzy != "|" else ""` expression is gone — the guard above replaces it.)

- [ ] **Step 4: Run seeder tests**

Run: `.venv/bin/pytest tests/test_seeder.py -v`
Expected: all 4 PASS.

- [ ] **Step 5: Amend the vault-import spec (docs truthfulness)**

In `docs/superpowers/specs/2026-07-03-vault-import-design.md`, in Import Behavior step 5, replace:

```markdown
5. **Seen-index marked:** URL row when `source_url` present; fuzzy key when company+title resolve (same `make_fuzzy_key`, same "|"-guard as the seeder). This is why a fully imported vault no longer needs the `existing_vault` seeder pointed at the old folder.
```

with:

```markdown
5. **Seen-index marked:** URL row when `source_url` present; fuzzy key when company+title resolve — 3-part `make_fuzzy_key(company, title, location)` when `location` is mapped and present, else `legacy_fuzzy_key(company, title)` (block-everywhere), with the same both-empty guard as the seeder. This is why a fully imported vault no longer needs the `existing_vault` seeder pointed at the old folder.
```

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `85 passed, 1 deselected`

- [ ] **Step 7: Commit**

```bash
git add job_pipeline/seeders/existing_vault.py tests/test_seeder.py docs/superpowers/specs/2026-07-03-vault-import-design.md
git commit -m "feat: seeder location_field — 3-part keys when mapped, legacy block-everywhere otherwise"
```

---

### Task 3: `score_floor` stage

**Files:**
- Modify: `job_pipeline/config.py` (Profile field)
- Create: `job_pipeline/stages/rules/score_floor.py`
- Modify: `job_pipeline/stages/rules/__init__.py` (import + `__all__`)
- Modify: `job_pipeline/core/pipeline.py` (`build_stages` deps entry)
- Modify: `config/profile.example.md`, `config/pipeline.example.yaml`, `README.md`
- Test: `tests/test_rule_stages.py` (4 added), `tests/test_pipeline_e2e.py` (1 added)

**Interfaces:**
- Consumes: `Profile` (gains `score_floor: int | None = None`), `Job.score`, existing `StageSpec`/`register_stage`.
- Produces: `ScoreFloorStage(profile)` registered as `"score_floor"` — Task 4 does not depend on it; nothing downstream consumes new fields.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rule_stages.py` (new section at the end):

```python
# --- score floor ---
def test_score_floor_rejects_below_floor():
    from job_pipeline.stages.rules import ScoreFloorStage
    out = ScoreFloorStage(profile(score_floor=60)).run(make_job(score=42.0))
    assert out.rejected and out.reject_stage == "score_floor"
    assert "42.0" in out.reject_reason and "60" in out.reject_reason


def test_score_floor_boundary_is_inclusive_keep():
    from job_pipeline.stages.rules import ScoreFloorStage
    assert not ScoreFloorStage(profile(score_floor=60)).run(make_job(score=60.0)).rejected


def test_score_floor_no_floor_passes():
    from job_pipeline.stages.rules import ScoreFloorStage
    assert not ScoreFloorStage(profile()).run(make_job(score=1.0)).rejected


def test_score_floor_no_score_passes_with_trace():
    from job_pipeline.stages.rules import ScoreFloorStage
    out = ScoreFloorStage(profile(score_floor=60)).run(make_job())
    assert not out.rejected
    assert any("no score present" in verdict for _, verdict, _ in out.trace)
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_rule_stages.py -k score_floor -v`
Expected: FAIL — `ImportError: cannot import name 'ScoreFloorStage'` (and `Profile` has no `score_floor` field).

- [ ] **Step 3: Add the Profile field**

In `job_pipeline/config.py`, in `class Profile`, add after the `salary_floor` line:

```python
    score_floor: int | None = None
```

- [ ] **Step 4: Create `job_pipeline/stages/rules/score_floor.py`**

```python
"""Reject jobs scoring below the profile's floor. Runs after score, before publish."""
from __future__ import annotations

from job_pipeline.config import Profile
from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_stage
from job_pipeline.core.stage import StageSpec


@register_stage("score_floor")
class ScoreFloorStage:
    spec = StageSpec("score_floor", "reject jobs scoring below the profile's floor",
                     requires=["score"], produces=["rejected"],
                     kind="deterministic", cost_tier="free")

    def __init__(self, profile: Profile) -> None:
        self.floor = profile.score_floor

    def run(self, job: Job) -> Job:
        if self.floor is None:
            job.add_trace("score_floor", "no floor configured")
            return job
        if job.score is None:
            job.add_trace("score_floor", "no score present; passed")
            return job
        if job.score >= self.floor:
            job.add_trace("score_floor", f"passed ({job.score} >= {self.floor})")
        else:
            job.mark_rejected("score_floor", f"score {job.score} below floor {self.floor}")
        return job
```

- [ ] **Step 5: Register in the package `__init__`**

In `job_pipeline/stages/rules/__init__.py`: add

```python
from job_pipeline.stages.rules.score_floor import ScoreFloorStage
```

with the other stage imports (alphabetical: after `salary`), and `"ScoreFloorStage",` to `__all__`.

- [ ] **Step 6: Wire `build_stages`**

In `job_pipeline/core/pipeline.py`, in the `deps` dict inside `build_stages`, add after the `"salary"` entry:

```python
        "score_floor": lambda c: c(profile),
```

- [ ] **Step 7: Run the new unit tests**

Run: `.venv/bin/pytest tests/test_rule_stages.py -k score_floor -v`
Expected: 4 PASS.

- [ ] **Step 8: Add the e2e test**

Append to `tests/test_pipeline_e2e.py`:

```python
def test_score_floor_rejects_low_scoring_job_terminally(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.stages = ["dedup", "hard_filter", "extract", "dedup_fuzzy",
                  "location", "salary", "skill_gap", "score", "score_floor", "publish"]
    prof = make_profile()
    prof.score_floor = 60
    db = tmp_path / "seen.sqlite"
    src = FakeSource([job("https://x.com/low", "ok listing")])
    summary = run_pipeline(cfg, prof, MockRunner([
        {"title": "T", "company": "C", "location": "Remote", "comp_text": "$150k",
         "comp_min": 150000, "comp_max": 150000, "comp_currency": "USD",
         "comp_period": "annual", "requirements": [], "description": "d"},
        {"have": [], "missing": [], "partial": []},
        {"score": 42.0, "rationale": "weak"},
    ]), sources=[src], db_path=db)
    assert summary.rejected == 1 and summary.published == 0
    assert summary.notes == []
    from job_pipeline.store.seen_index import SeenIndex
    assert SeenIndex(db).count() == 1        # terminal: marked seen
```

- [ ] **Step 9: Example configs + README**

In `config/profile.example.md` frontmatter, add after the `salary_floor: 100000` line:

```yaml
# score_floor: 60        # optional: reject scored jobs below this (terminal — see README)
```

In `config/pipeline.example.yaml`, add a comment line directly above the `stages:` line:

```yaml
# optional stage: add score_floor between score and publish (set score_floor in profile.md)
```

In `README.md`, in section "### 1. Config-driven stages", append after the line `Add, remove, or reorder stages with a config edit.`:

```markdown
One optional stage ships disabled: add `score_floor` between `score` and `publish`
(with `score_floor: 60` in `profile.md`) to keep below-floor jobs out of your vault.
A score-floor rejection is terminal — the URL is marked seen and won't be re-scored,
and raising the floor later doesn't resurrect past rejects (re-run one deliberately
with `--reprocess`).
```

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `90 passed, 1 deselected`

- [ ] **Step 11: Commit**

```bash
git add job_pipeline/config.py job_pipeline/stages/rules/ job_pipeline/core/pipeline.py config/ README.md tests/
git commit -m "feat: score_floor stage — reject below-floor scores before publish"
```

---

### Task 4: `SeenIndex.unmark` + CLI `--reprocess`

**Files:**
- Modify: `job_pipeline/store/seen_index.py` (add `unmark`)
- Modify: `job_pipeline/cli.py` (flag, validation, unmark loop)
- Modify: `README.md` (run examples block)
- Test: `tests/test_seen_index.py` (2 added), `tests/test_cli.py` (2 added), `tests/test_pipeline_e2e.py` (1 added)

**Interfaces:**
- Consumes: existing `SeenIndex` connection plumbing; existing `tests/test_cli.py` helpers (`PROFILE` constant, `cli.main`, monkeypatched `cli.run_pipeline`).
- Produces: `SeenIndex.unmark(url_hash: str) -> bool` (row deleted → True; unknown hash → False). CLI: `run --reprocess` valid only with `--url`.

- [ ] **Step 1: Write the failing store tests**

Append to `tests/test_seen_index.py`:

```python
def test_unmark_removes_url_and_its_fuzzy_key(tmp_path):
    idx = SeenIndex(tmp_path / "seen.sqlite")
    idx.mark("abc", "acme|engineer|remote")
    idx.mark("other", "beta|dev|nyc")
    assert idx.unmark("abc") is True
    assert not idx.has_url("abc")
    assert not idx.has_fuzzy("acme|engineer|remote")   # same row, one delete
    assert idx.has_url("other")                        # untouched


def test_unmark_unknown_hash_returns_false(tmp_path):
    idx = SeenIndex(tmp_path / "seen.sqlite")
    assert idx.unmark("nope") is False
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_seen_index.py -v`
Expected: FAIL with `AttributeError: 'SeenIndex' object has no attribute 'unmark'`.

- [ ] **Step 3: Add `unmark`**

In `job_pipeline/store/seen_index.py`, add after `mark`:

```python
    def unmark(self, url_hash: str) -> bool:
        """Delete the row for url_hash; returns whether a row existed.

        Deliberate escape hatch (--reprocess): removing the row also clears
        its fuzzy_key, so the re-run redoes URL AND fuzzy dedup for this entry.
        """
        cur = self._conn().execute("DELETE FROM seen WHERE url_hash = ?", (url_hash,))
        self._conn().commit()
        return cur.rowcount > 0
```

- [ ] **Step 4: Run store tests**

Run: `.venv/bin/pytest tests/test_seen_index.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing CLI tests**

Append to `tests/test_cli.py`:

```python
def test_reprocess_requires_url(tmp_path):
    import pytest
    cfg, prof = _write_configs(tmp_path)
    with pytest.raises(SystemExit):
        cli.main(["run", "--config", str(cfg), "--profile", str(prof),
                  "--mock", "--reprocess"])


def test_reprocess_clears_seen_row_before_run(monkeypatch, tmp_path):
    import hashlib
    from job_pipeline.store.seen_index import SeenIndex
    vault = tmp_path / "vault"
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text(
        "stages: [dedup]\n"
        f"output: {{vault: {vault}}}\n"
        "models: {extract: haiku, skill_gap: sonnet, score: opus}\n"
    )
    prof = tmp_path / "profile.md"
    prof.write_text(PROFILE)
    url = "https://example.com/job/1"
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    idx = SeenIndex(vault / ".job_pipeline.seen.sqlite")
    idx.mark(h)
    idx.close()

    def fake_run_pipeline(*args, **kwargs):
        from job_pipeline.core.pipeline import RunSummary
        return RunSummary()

    monkeypatch.setattr(cli, "run_pipeline", fake_run_pipeline)
    rc = cli.main(["run", "--config", str(cfg), "--profile", str(prof),
                   "--mock", "--url", url, "--reprocess"])
    assert rc == 0
    assert not SeenIndex(vault / ".job_pipeline.seen.sqlite").has_url(h)
```

- [ ] **Step 6: Run to verify failure**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: the two new tests FAIL — `--reprocess` is an unrecognized argument (argparse exits for the *wrong* reason in test 1; after implementation it must exit for the right reason — the second test failing on unrecognized argument is the discriminating check).

- [ ] **Step 7: Implement the flag**

In `job_pipeline/cli.py`: add after the `--url` argument (line 18-19):

```python
    run.add_argument("--reprocess", action="store_true",
                     help="clear the seen-index entry for each --url before running")
```

Add directly after `args = parser.parse_args(argv)`:

```python
    if args.reprocess and not args.url:
        parser.error("--reprocess requires --url (no blanket un-marking)")
```

Add after `cfg = load_pipeline_config(args.config)` (needs the vault path):

```python
    if args.reprocess:
        import hashlib
        from job_pipeline.store.seen_index import SeenIndex
        seen = SeenIndex(cfg.output.vault.expanduser() / ".job_pipeline.seen.sqlite")
        for url in args.url:
            was = seen.unmark(hashlib.sha256(url.encode()).hexdigest()[:16])
            logging.info("reprocessing %s (%s)", url, "was seen" if was else "was not seen")
        seen.close()
```

- [ ] **Step 8: Run CLI tests**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: all PASS (including the two pre-existing tests).

- [ ] **Step 9: Add the full-cycle e2e test**

Append to `tests/test_pipeline_e2e.py`:

```python
def test_unmark_lets_a_seen_url_republish(tmp_path):
    cfg, prof = make_cfg(tmp_path), make_profile()
    db = tmp_path / "seen.sqlite"
    replies = [
        {"title": "T", "company": "C", "location": "Remote", "comp_text": "$150k",
         "comp_min": 150000, "comp_max": 150000, "comp_currency": "USD",
         "comp_period": "annual", "requirements": [], "description": "d"},
        {"have": [], "missing": [], "partial": []},
        {"score": 90.0, "rationale": "ok"},
    ]
    url = "https://x.com/1"
    s1 = run_pipeline(cfg, prof, MockRunner(list(replies)),
                      sources=[FakeSource([job(url, "listing")])], db_path=db)
    assert s1.published == 1
    s2 = run_pipeline(cfg, prof, MockRunner([]),
                      sources=[FakeSource([job(url, "listing")])], db_path=db)
    assert s2.rejected == 1                      # dedup: seen
    from job_pipeline.store.seen_index import SeenIndex
    import hashlib
    SeenIndex(db).unmark(hashlib.sha256(url.encode()).hexdigest()[:16])
    s3 = run_pipeline(cfg, prof, MockRunner(list(replies)),
                      sources=[FakeSource([job(url, "listing")])], db_path=db)
    assert s3.published == 1                     # reprocessed successfully
```

- [ ] **Step 10: README run examples**

In `README.md`, in the "### Run the pipeline" code block, add after the `--url https://... --mock` line:

```bash
job-pipeline run --url https://... --reprocess   # re-run a previously processed URL (clears its seen entry; add --force to also overwrite an edited note)
```

- [ ] **Step 11: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `95 passed, 1 deselected`

- [ ] **Step 12: Commit**

```bash
git add job_pipeline/store/seen_index.py job_pipeline/cli.py README.md tests/
git commit -m "feat: SeenIndex.unmark + run --reprocess for deliberate re-runs"
```

---

## Verification (whole plan)

- `.venv/bin/pytest -q` → `95 passed, 1 deselected`
- `git diff <base>..HEAD --stat` touches no files outside: `job_pipeline/{stages/rules,seeders,store,core/pipeline.py,config.py,cli.py}`, `config/*.example.*`, `README.md`, `tests/`, and the one vault-import spec line.
- Smoke: `.venv/bin/python -c "from job_pipeline.stages.rules import make_fuzzy_key, legacy_fuzzy_key, ScoreFloorStage; from job_pipeline.core.registry import get_stage; get_stage('score_floor'); print('ok')"` → `ok`
