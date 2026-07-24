# Batch B — Vault Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Published notes carry comp, location, and duplicate-signal frontmatter plus a `## Compensation` section and a user-owned `application_status` field; a zero-token `job-pipeline import` command adopts an existing tracker folder into the vault.

**Architecture:** Implements three approved specs — `2026-07-03-comp-in-notes-design.md`, `2026-07-03-application-status-design.md`, `2026-07-03-vault-import-design.md` — as one batch with a single golden-test rebase. Post-Batch-L deviations (binding, supersede the specs where they conflict): `HOURS_PER_YEAR` no longer exists in `stages/rules` (deleted with the salary gate) — it is re-declared as a module constant in `store/obsidian.py`; the roadmap-mandated lean-core rebase adds `location`, `role_key`, and `possible_duplicate` frontmatter (surfacing data the lean core keeps but publish previously dropped); `location` is added to vault-import's mappable canonicals (the spec's fuzzy-key step references it but its list predates the location key).

**Tech Stack:** Python 3.12, pydantic v2, PyYAML, pytest. No network, no model tokens in tests.

## Global Constraints

- **Binding frontmatter order** (all note-writing code and tests; `sort_keys=False`):
  `company, position, location, employer_address, employer_phone, employer_email, employer_contact_person, date_found, date_of_contact, source_url, type_of_work, result_of_contact, application_status, score, comp_min, comp_max, comp_currency, comp_period, status, job_id, role_key, possible_duplicate`
- **Binding body order:** `## Fit`, `## Compensation`, `## Skill gap`, `## Description`.
- All frontmatter keys always present (null/empty when absent) — identical schema on every note, no Dataview existence guards.
- `application_status` is free text, never validated, never advanced by the pipeline (no-auto-apply is a project invariant).
- Import spends zero tokens, never runs stages, never overwrites an existing note (no `--force` for import — fixing an import means deleting the generated note and re-running).
- Tests must not use network or real model calls.
- Run tests with `.venv/bin/pytest` from the worktree root (worktree venvs; plain `pytest` is not on PATH).
- Commit after every task; messages use `feat:`/`docs:` prefixes, imperative mood.

---

### Task 1: Note schema — comp, location, duplicate signal, application_status, skip-on-edit

**Files:**
- Modify: `job_pipeline/store/obsidian.py`
- Test: `tests/test_publish.py`

**Interfaces:**
- Consumes: `Job` fields (`comp_min/comp_max/comp_currency/comp_period/comp_text`, `location`, `fuzzy_key`, `trace`) — all already exist.
- Produces: `format_comp(job: Job) -> str` (pure helper, module level); `HOURS_PER_YEAR = 2080` module constant in `store/obsidian.py`; the full binding frontmatter schema above; `is_user_touched` returns True when `status != "to_review"` OR `application_status != "Unsubmitted"` (missing key counts as `"Unsubmitted"`). Tasks 3-4 rely on this exact schema and on `_slug` remaining importable from this module.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_publish.py` (keep the four existing tests; the fixture `scored_job()` gains nothing — variations are built per-test):

```python
def comp_job(**kw):
    j = scored_job()
    j.comp_text = kw.pop("comp_text", "")
    for k, v in kw.items():
        setattr(j, k, v)
    return j


# --- format_comp ---
def test_format_comp_range_annual():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=150000, comp_max=180000, comp_currency="USD", comp_period="annual")
    assert format_comp(j) == "$150,000–$180,000 USD (annual)"


def test_format_comp_single_value():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=150000, comp_max=150000, comp_currency="USD", comp_period="annual")
    assert format_comp(j) == "$150,000 USD (annual)"


def test_format_comp_hourly_annualizes():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=35, comp_max=40, comp_currency="USD", comp_period="hourly")
    assert format_comp(j) == "$35–$40 USD/hr (≈ $72,800–$83,200 annualized)"


def test_format_comp_non_usd_no_dollar_sign():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=150000, comp_max=180000, comp_currency="EUR", comp_period="annual")
    assert format_comp(j) == "150,000–180,000 EUR (annual)"


def test_format_comp_not_listed():
    from job_pipeline.store.obsidian import format_comp
    assert format_comp(comp_job()) == "Not listed"


def test_format_comp_not_listed_with_text():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_text="competitive + equity")
    assert format_comp(j) == 'Not listed — listed text: "competitive + equity"'


def test_format_comp_provenance_appended_when_text_present():
    from job_pipeline.store.obsidian import format_comp
    j = comp_job(comp_min=150000, comp_max=180000, comp_currency="USD",
                 comp_period="annual", comp_text="$150k-$180k")
    assert format_comp(j) == '$150,000–$180,000 USD (annual) (listed as "$150k-$180k")'


# --- new frontmatter schema ---
BINDING_ORDER = [
    "company", "position", "location", "employer_address", "employer_phone",
    "employer_email", "employer_contact_person", "date_found", "date_of_contact",
    "source_url", "type_of_work", "result_of_contact", "application_status",
    "score", "comp_min", "comp_max", "comp_currency", "comp_period",
    "status", "job_id", "role_key", "possible_duplicate",
]


def test_frontmatter_matches_binding_order_and_new_keys(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    j.comp_min, j.comp_max = 150000, 180000
    j.comp_currency, j.comp_period = "USD", "annual"
    j.fuzzy_key = "acmecorp|seniorengineer|remote"
    path = w.write(j)
    fm = read_frontmatter(path)
    assert list(fm.keys()) == BINDING_ORDER
    assert fm["location"] == "Remote"
    assert fm["comp_min"] == 150000 and fm["comp_max"] == 180000
    assert fm["application_status"] == "Unsubmitted"
    assert fm["role_key"] == "acmecorp|seniorengineer|remote"
    assert fm["possible_duplicate"] is False


def test_frontmatter_nulls_when_absent(tmp_path):
    w = ObsidianWriter(tmp_path)
    path = w.write(scored_job())    # no comp numbers, no fuzzy key
    fm = read_frontmatter(path)
    assert fm["comp_min"] is None and fm["comp_max"] is None
    assert fm["comp_currency"] is None and fm["comp_period"] is None
    assert fm["role_key"] is None


def test_possible_duplicate_true_from_trace(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    j.fuzzy_key = "acmecorp|seniorengineer|remote"
    j.add_trace("dedup_fuzzy", "possible duplicate: acmecorp|seniorengineer|remote")
    fm = read_frontmatter(w.write(j))
    assert fm["possible_duplicate"] is True


def test_body_has_compensation_section_in_order(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    j.comp_min = j.comp_max = 150000
    j.comp_currency, j.comp_period = "USD", "annual"
    text = w.write(j).read_text()
    fit = text.index("## Fit")
    comp = text.index("## Compensation")
    gap = text.index("## Skill gap")
    desc = text.index("## Description")
    assert fit < comp < gap < desc
    assert "$150,000 USD (annual)" in text


# --- skip-on-edit extension ---
def test_user_touched_when_application_status_advanced(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    path = w.write(j)
    path.write_text(path.read_text().replace(
        "application_status: Unsubmitted", "application_status: Submitted"))
    assert w.is_user_touched(j)


def test_not_touched_when_fresh(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    w.write(j)
    assert not w.is_user_touched(j)


def test_legacy_note_without_application_status_uses_status_only(tmp_path):
    w = ObsidianWriter(tmp_path)
    j = scored_job()
    path = w.write(j)
    # simulate a pre-feature note: drop the application_status line entirely
    path.write_text(path.read_text().replace("application_status: Unsubmitted\n", ""))
    assert not w.is_user_touched(j)
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv/bin/pytest tests/test_publish.py -v`
Expected: all new tests FAIL (`format_comp` not defined; missing keys); the four pre-existing tests PASS.

- [ ] **Step 3: Implement in `store/obsidian.py`**

Add after `_slug`:

```python
HOURS_PER_YEAR = 2080   # annualizes hourly comp for display (salary gate deleted in Batch L)


def format_comp(job: Job) -> str:
    """Human-readable comp line for the ## Compensation section."""
    lo, hi = job.comp_min, job.comp_max
    if lo is None and hi is None:
        if job.comp_text:
            return f'Not listed — listed text: "{job.comp_text}"'
        return "Not listed"
    values = [lo, hi] if (lo is not None and hi is not None and lo != hi) \
        else [hi if hi is not None else lo]
    dollar = "$" if job.comp_currency in (None, "USD") else ""
    amounts = "–".join(f"{dollar}{v:,}" for v in values)
    label = f" {job.comp_currency}" if job.comp_currency else ""
    if job.comp_period == "hourly":
        annualized = "–".join(f"{dollar}{v * HOURS_PER_YEAR:,}" for v in values)
        text = f"{amounts}{label}/hr (≈ {annualized} annualized)"
    elif job.comp_period == "annual":
        text = f"{amounts}{label} (annual)"
    else:
        text = f"{amounts}{label}"
    if job.comp_text:
        text += f' (listed as "{job.comp_text}")'
    return text
```

Replace the `frontmatter` dict and `body` in `write()` with:

```python
        possible_dup = any(
            stage == "dedup_fuzzy" and verdict.startswith("possible duplicate")
            for stage, verdict, _ in job.trace
        )
        frontmatter = {
            "company": job.company,
            "position": job.title,
            "location": job.location,
            "employer_address": job.employer_address,
            "employer_phone": job.employer_phone,
            "employer_email": job.employer_email,
            "employer_contact_person": "",
            "date_found": job.fetched_at.date().isoformat(),
            "date_of_contact": "",
            "source_url": job.url,
            "type_of_work": job.title,
            "result_of_contact": "found",
            "application_status": "Unsubmitted",
            "score": job.score,
            "comp_min": job.comp_min,
            "comp_max": job.comp_max,
            "comp_currency": job.comp_currency,
            "comp_period": job.comp_period,
            "status": "to_review",
            "job_id": job.id,
            "role_key": job.fuzzy_key or None,
            "possible_duplicate": possible_dup,
        }
        gap = job.skill_gap or {}
        body = (
            f"## Fit — {job.score}/100\n{job.score_rationale}\n\n"
            f"## Compensation\n{format_comp(job)}\n\n"
            f"## Skill gap\n"
            f"- Have: {', '.join(gap.get('have', []))}\n"
            f"- Missing: {', '.join(gap.get('missing', []))}\n"
            f"- Partial: {', '.join(gap.get('partial', []))}\n\n"
            f"## Description\n{job.description}\n"
        )
```

Replace `is_user_touched`'s return with:

```python
        try:
            _, fm, _ = text.split("---", 2)
            data = yaml.safe_load(fm) or {}
            return (data.get("status") != "to_review"
                    or data.get("application_status", "Unsubmitted") != "Unsubmitted")
        except ValueError:
            return True   # malformed note: treat as user-owned, never clobber
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all PASS (existing publish/e2e tests assert content by key, not full golden text — no other rebase needed).

- [ ] **Step 5: Commit**

```bash
git add job_pipeline/store/obsidian.py tests/test_publish.py
git commit -m "feat: note schema — comp keys+section, location, role_key/possible_duplicate, application_status with skip-on-edit"
```

---

### Task 2: `import:` config block

**Files:**
- Modify: `job_pipeline/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `ImportConfig(BaseModel)` with `path: Path`, `fields: dict[str, str] = {}`, `keep_unmapped: bool = True`; `CANONICAL_IMPORT_KEYS: frozenset[str]`; `PipelineConfig.import_: ImportConfig | None = Field(default=None, alias="import")`. Tasks 3-4 consume `cfg.import_`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_config.py`:

```python
IMPORT_BLOCK = """
import:
  path: /tmp/old-tracker
  fields:
    company: company
    position: position
    application_status: status
    date_of_contact: date-applied
    source_url: website
  keep_unmapped: true
"""


def test_import_block_parses(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE + IMPORT_BLOCK)
    cfg = load_pipeline_config(p)
    assert cfg.import_ is not None
    assert cfg.import_.fields["application_status"] == "status"
    assert cfg.import_.keep_unmapped is True


def test_import_block_absent_is_none(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE)
    assert load_pipeline_config(p).import_ is None


def test_import_unknown_canonical_fails_naming_key(tmp_path):
    p = tmp_path / "pipeline.yaml"
    p.write_text(PIPELINE + IMPORT_BLOCK.replace("company: company", "bogus: company"))
    with pytest.raises(ValidationError, match="bogus"):
        load_pipeline_config(p)
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: three new tests FAIL (`import_` attribute missing); rest PASS.

- [ ] **Step 3: Implement in `config.py`**

Add above `PipelineConfig`:

```python
CANONICAL_IMPORT_KEYS = frozenset({
    "company", "position", "location", "type_of_work", "source_url",
    "date_found", "date_of_contact", "employer_address", "employer_phone",
    "employer_email", "employer_contact_person", "result_of_contact",
    "application_status", "score",
})


class ImportConfig(BaseModel):
    path: Path
    fields: dict[str, str] = {}
    keep_unmapped: bool = True

    @field_validator("fields")
    @classmethod
    def _only_canonical_keys(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(v) - CANONICAL_IMPORT_KEYS)
        if unknown:
            raise ValueError(f"unknown canonical import field(s): {', '.join(unknown)}")
        return v
```

Add to `PipelineConfig` (after `limits`), plus the `Field` import if not present:

```python
    import_: ImportConfig | None = Field(default=None, alias="import")
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add job_pipeline/config.py tests/test_config.py
git commit -m "feat: import: config block — canonical field map, keep_unmapped"
```

---

### Task 3: Importer module

**Files:**
- Create: `job_pipeline/store/vault_import.py`
- Test: `tests/test_vault_import.py` (new)

**Interfaces:**
- Consumes: `cfg.import_` (Task 2), `_slug` from `store/obsidian.py` (Task 1 keeps it), `SeenIndex.mark/has_url/has_fuzzy`, `make_fuzzy_key`/`legacy_fuzzy_key` from `job_pipeline.stages.rules`.
- Produces: `run_import(cfg: PipelineConfig, dry_run: bool = False) -> ImportSummary` where `ImportSummary` is a dataclass with `imported`, `skipped_existing`, `skipped_unparseable`, `seen_marked` ints and `planned: list[tuple[Path, Path]]` (old → new, dry-run only). Task 4's CLI consumes both.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_import.py`:

```python
from pathlib import Path
import hashlib
import yaml
from job_pipeline.config import PipelineConfig, OutputConfig, ImportConfig
from job_pipeline.store.seen_index import SeenIndex
from job_pipeline.store.vault_import import run_import

OLD_NOTE = """---
position: Software Engineer
company: OldCo
status: In Talks
date-applied: 2025-11-02
website: https://oldco.example/careers/123
has-referral: true
---
## Notes
Talked to recruiter on 11/2.
"""

FIELDS = {
    "company": "company",
    "position": "position",
    "application_status": "status",
    "date_of_contact": "date-applied",
    "source_url": "website",
}


def make_cfg(tmp_path, **import_kw):
    old = tmp_path / "old"
    old.mkdir(exist_ok=True)
    kw = dict(path=old, fields=FIELDS, keep_unmapped=True)
    kw.update(import_kw)
    return PipelineConfig(
        stages=["dedup"], output=OutputConfig(vault=tmp_path / "vault"),
        **{"import": ImportConfig(**kw)},
    ), old


def read_note(vault):
    notes = list(Path(vault).glob("*.md"))
    assert len(notes) == 1
    text = notes[0].read_text()
    _, fm, body = text.split("---", 2)
    return notes[0], yaml.safe_load(fm), body


def test_import_maps_fields_and_preserves_body(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    s = run_import(cfg)
    assert s.imported == 1
    path, fm, body = read_note(tmp_path / "vault")
    assert fm["company"] == "OldCo"
    assert fm["position"] == "Software Engineer"
    assert fm["application_status"] == "In Talks"
    assert str(fm["date_of_contact"]) == "2025-11-02"
    assert fm["source_url"] == "https://oldco.example/careers/123"
    assert fm["status"] == "imported"          # never to_review
    assert fm["has-referral"] is True           # keep_unmapped carried through
    assert body == "\n## Notes\nTalked to recruiter on 11/2.\n"  # byte-exact
    assert path.name.startswith("oldco-software-engineer-")


def test_import_drop_unmapped_when_disabled(tmp_path):
    cfg, old = make_cfg(tmp_path, keep_unmapped=False)
    (old / "oldco.md").write_text(OLD_NOTE)
    run_import(cfg)
    _, fm, _ = read_note(tmp_path / "vault")
    assert "has-referral" not in fm


def test_import_is_idempotent(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    assert run_import(cfg).imported == 1
    s2 = run_import(cfg)
    assert s2.imported == 0 and s2.skipped_existing == 1


def test_import_marks_seen_url_and_fuzzy(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    s = run_import(cfg)
    assert s.seen_marked == 1
    idx = SeenIndex(tmp_path / "vault" / ".job_pipeline.seen.sqlite")
    h = hashlib.sha256(b"https://oldco.example/careers/123").hexdigest()[:16]
    assert idx.has_url(h)
    assert idx.has_fuzzy("oldco|softwareengineer")   # legacy 2-part: no location mapped


def test_import_urlless_note_keys_by_relative_path(tmp_path):
    cfg, old = make_cfg(tmp_path)
    note = OLD_NOTE.replace("website: https://oldco.example/careers/123\n", "")
    (old / "oldco.md").write_text(note)
    assert run_import(cfg).imported == 1
    _, fm, _ = read_note(tmp_path / "vault")
    assert fm["job_id"] == hashlib.sha256(b"oldco.md").hexdigest()[:16]
    assert run_import(cfg).imported == 0    # stable id across runs


def test_import_skips_unparseable(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "not-a-note.md").write_text("just some text, no frontmatter")
    s = run_import(cfg)
    assert s.imported == 0 and s.skipped_unparseable == 1


def test_dry_run_writes_nothing(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    s = run_import(cfg, dry_run=True)
    assert s.imported == 1 and len(s.planned) == 1
    assert not list((tmp_path / "vault").glob("*.md"))
    assert SeenIndex(tmp_path / "vault" / ".job_pipeline.seen.sqlite").count() == 0
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv/bin/pytest tests/test_vault_import.py -v`
Expected: FAIL with `ModuleNotFoundError: job_pipeline.store.vault_import`.

- [ ] **Step 3: Implement `job_pipeline/store/vault_import.py`**

```python
"""job-pipeline import — adopt an existing tracker folder into the vault.

Zero tokens, no stages, never overwrites. Distinct from the existing_vault
seeder: the seeder makes the pipeline IGNORE old jobs; import ADOPTS them.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from job_pipeline.config import PipelineConfig
from job_pipeline.stages.rules import legacy_fuzzy_key, make_fuzzy_key
from job_pipeline.store.obsidian import _slug
from job_pipeline.store.seen_index import SeenIndex


@dataclass
class ImportSummary:
    imported: int = 0
    skipped_existing: int = 0
    skipped_unparseable: int = 0
    seen_marked: int = 0
    planned: list[tuple[Path, Path]] = field(default_factory=list)


def _new_frontmatter(mapped: dict, job_id: str, fuzzy: str) -> dict:
    position = str(mapped.get("position", ""))
    fm = {
        "company": mapped.get("company", ""),
        "position": position,
        "location": mapped.get("location", ""),
        "employer_address": mapped.get("employer_address", ""),
        "employer_phone": mapped.get("employer_phone", ""),
        "employer_email": mapped.get("employer_email", ""),
        "employer_contact_person": mapped.get("employer_contact_person", ""),
        "date_found": mapped.get("date_found", ""),
        "date_of_contact": mapped.get("date_of_contact", ""),
        "source_url": mapped.get("source_url", ""),
        "type_of_work": mapped.get("type_of_work", position),
        "result_of_contact": mapped.get("result_of_contact", "found"),
        "application_status": mapped.get("application_status", "Unsubmitted"),
        "score": mapped.get("score"),
        "comp_min": None,
        "comp_max": None,
        "comp_currency": None,
        "comp_period": None,
        "status": "imported",   # never to_review: permanently protected by skip-on-edit
        "job_id": job_id,
        "role_key": fuzzy or None,
        "possible_duplicate": False,
    }
    return fm


def run_import(cfg: PipelineConfig, dry_run: bool = False) -> ImportSummary:
    imp = cfg.import_
    vault = cfg.output.vault.expanduser()
    root = imp.path.expanduser()
    summary = ImportSummary()
    seen = SeenIndex(vault / ".job_pipeline.seen.sqlite")
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)
    for note in sorted(root.rglob("*.md")):
        text = note.read_text()
        if not text.startswith("---"):
            summary.skipped_unparseable += 1
            continue
        try:
            _, fm_text, body = text.split("---", 2)
            old = yaml.safe_load(fm_text) or {}
        except (ValueError, yaml.YAMLError):
            summary.skipped_unparseable += 1
            continue
        mapped = {canon: old[key] for canon, key in imp.fields.items() if key in old}
        url = str(mapped.get("source_url") or "")
        if url:
            job_id = hashlib.sha256(url.encode()).hexdigest()[:16]
        else:
            job_id = hashlib.sha256(
                str(note.relative_to(root)).encode()).hexdigest()[:16]
        company = str(mapped.get("company", ""))
        title = str(mapped.get("position", ""))
        loc = str(mapped.get("location", ""))
        if legacy_fuzzy_key(company, title) == "|":
            fuzzy = ""
        elif loc:
            fuzzy = make_fuzzy_key(company, title, loc)
        else:
            fuzzy = legacy_fuzzy_key(company, title)   # block-everywhere semantics
        target = vault / f"{_slug(company)}-{_slug(title)}-{job_id[:8]}.md"
        if target.exists():
            summary.skipped_existing += 1
            continue
        if dry_run:
            summary.imported += 1
            summary.planned.append((note, target))
            continue
        new_fm = _new_frontmatter(mapped, job_id, fuzzy)
        if imp.keep_unmapped:
            consumed = set(imp.fields.values())
            for key, value in old.items():
                if key not in consumed and key not in new_fm:
                    new_fm[key] = value
        target.write_text(
            "---\n" + yaml.safe_dump(new_fm, sort_keys=False) + "---" + body
        )
        summary.imported += 1
        if url or fuzzy:
            seen.mark(job_id, fuzzy)
            summary.seen_marked += 1
    seen.close()
    return summary
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all PASS. If the body byte-exactness test fails on the `"---" + body` join, check the split remainder — `text.split("---", 2)` leaves the body starting with `"\n"`, so the join must NOT add its own newline (the expected value in the test reflects this).

- [ ] **Step 5: Commit**

```bash
git add job_pipeline/store/vault_import.py tests/test_vault_import.py
git commit -m "feat: vault import — zero-token adoption of an existing tracker"
```

---

### Task 4: CLI `import` command, example config, README

**Files:**
- Modify: `job_pipeline/cli.py`, `config/pipeline.example.yaml`, `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_import`/`ImportSummary` (Task 3), `cfg.import_` (Task 2).
- Produces: `job-pipeline import [--config ...] [--dry-run]`; exits 2 with a clear message when no `import:` block.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_cli.py`:

```python
OLD_NOTE = """---
position: Engineer
company: OldCo
website: https://oldco.example/1
---
Body.
"""

IMPORT_YAML = """
stages: [dedup]
models: {{extract: haiku, skill_gap: sonnet, score: opus}}
output: {{vault: {vault}}}
import:
  path: {old}
  fields:
    company: company
    position: position
    source_url: website
"""


def test_import_command_imports(tmp_path, capsys):
    old = tmp_path / "old"
    old.mkdir()
    (old / "a.md").write_text(OLD_NOTE)
    vault = tmp_path / "vault"
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text(IMPORT_YAML.format(vault=vault, old=old))
    rc = cli.main(["import", "--config", str(cfg)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "imported=1 skipped_existing=0 skipped_unparseable=0 seen_marked=1" in out
    assert len(list(vault.glob("*.md"))) == 1


def test_import_dry_run_writes_nothing(tmp_path, capsys):
    old = tmp_path / "old"
    old.mkdir()
    (old / "a.md").write_text(OLD_NOTE)
    vault = tmp_path / "vault"
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text(IMPORT_YAML.format(vault=vault, old=old))
    rc = cli.main(["import", "--config", str(cfg), "--dry-run"])
    assert rc == 0
    assert "->" in capsys.readouterr().out       # per-note plan printed
    assert not list(vault.glob("*.md"))


def test_import_errors_without_block(tmp_path, capsys):
    cfg, _ = _write_configs(tmp_path)             # PIPELINE has no import: block
    rc = cli.main(["import", "--config", str(cfg)])
    assert rc == 2
    assert "import" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify failures**

Run: `.venv/bin/pytest tests/test_cli.py -v`
Expected: three new tests FAIL (unknown command `import`); existing four PASS.

- [ ] **Step 3: Implement the CLI branch**

In `cli.py`, add `import sys` at the top, register the subcommand after the `run` parser setup:

```python
    imp = sub.add_parser("import", help="convert an existing tracker folder into pipeline notes")
    imp.add_argument("--config", type=Path, default=Path("config/pipeline.yaml"))
    imp.add_argument("--dry-run", action="store_true",
                     help="print the per-note plan without writing anything")
```

and branch immediately after `args = parser.parse_args(argv)` — but before the `run`-specific `--reprocess` validation (which reads attributes the import namespace lacks):

```python
    if args.cmd == "import":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        cfg = load_pipeline_config(args.config)
        if cfg.import_ is None:
            print("error: config has no `import:` block — see README "
                  "'Importing an existing tracker'", file=sys.stderr)
            return 2
        from job_pipeline.store.vault_import import run_import
        s = run_import(cfg, dry_run=args.dry_run)
        if args.dry_run:
            for old, new in s.planned:
                print(f"  {old} -> {new}")
        print(f"imported={s.imported} skipped_existing={s.skipped_existing} "
              f"skipped_unparseable={s.skipped_unparseable} seen_marked={s.seen_marked}")
        return 0
```

- [ ] **Step 4: Update `config/pipeline.example.yaml`**

Append a commented block:

```yaml
# One-time adoption of an existing tracker folder (job-pipeline import):
# import:
#   path: ~/Documents/old-job-tracker      # folder of old notes (recursive)
#   fields:                                # pipeline-canonical <- old frontmatter key
#     company: company
#     position: position
#     application_status: status
#     date_of_contact: date-applied
#     source_url: website
#   keep_unmapped: true                    # carry unrecognized old keys through
```

- [ ] **Step 5: Update `README.md`**

Read the README first, then add:

- An "Importing an existing tracker" subsection (near the seeder docs): what `job-pipeline import` does (config-driven remap, body preserved, `status: imported`, seen-index marked, idempotent, `--dry-run`), plus the two-liner: *the `existing_vault` seeder makes the pipeline ignore old jobs (notes stay put); `import` adopts them into the output vault. Both remain.*
- The three-lifecycle table from the application-status spec, verbatim:

```markdown
| Field | Owner | Meaning |
|---|---|---|
| `status` | pipeline ↔ user | note lifecycle: `to_review` until you triage it; advancing it arms skip-on-edit |
| `result_of_contact` | user (VEC) | VEC contact-record language: `found` → `applied` → `interview` → … |
| `application_status` | user | application lifecycle: `Unsubmitted` → `Submitted` → `In Talks` → `Denied`/`Offered`/`Accepted` |
```

with the note that `application_status` is free text (suggested vocabulary: `Unsubmitted`, `Submitted`, `In Talks`, `Denied`, `Offered`, `Accepted` — add your own like `Ghosted`/`Withdrawn` without touching code).
- Mention the new note content where the README describes published notes: comp frontmatter keys + `## Compensation` section, `location`, `role_key`/`possible_duplicate`.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/pytest`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add job_pipeline/cli.py tests/test_cli.py config/pipeline.example.yaml README.md
git commit -m "feat: job-pipeline import command + docs"
```

---

## Post-plan notes for the executor

- Branch: `feat/batch-b-vault-output` off current main; Ryan pushes/PRs/merges himself — do not push.
- Worktree venv: create with `python -m venv .venv` from the main checkout's `.venv/bin/python`, then `.venv/bin/pip install -e ".[dev]"`.
- The live vault at `~/Documents/TekGadgt-Remote/job_application_pipeline/` is real user data — never run `import` or `run` against it during development.
- Ryan's live gitignored `config/pipeline.yaml` needs no changes for this batch (import block is opt-in; he'll add his own when ready to import his old tracker).
