# Stage Package Refactor — Design Spec

**Date:** 2026-07-02
**Status:** Approved for planning
**Scope:** Pure mechanical refactor. No behavior change, no new features, no test-logic changes.

## Goal

Split the two multi-stage modules — `job_pipeline/stages/rules.py` and `job_pipeline/stages/agents.py` — into packages with one stage per module, so the "add your own stage" story for the public repo is: *copy one small file, register it, list it in `pipeline.yaml`*.

## Motivation

The orchestrator, sources, and seeders are all modular seams; the stages themselves are the only place where five (rules) or three (agents) independent units share a file. One-file-per-stage makes each stage independently readable, copyable as a template, and diffable in review.

## Target Layout

```
job_pipeline/stages/
  __init__.py            # unchanged (empty)
  publish.py             # unchanged
  rules/
    __init__.py          # imports every submodule; re-exports public names
    common.py            # make_fuzzy_key, HOURS_PER_YEAR
    dedup.py             # DedupStage
    hard_filter.py       # HardFilterStage
    dedup_fuzzy.py       # FuzzyDedupStage (imports make_fuzzy_key from .common)
    location.py          # LocationStage
    salary.py            # SalaryStage (imports HOURS_PER_YEAR from .common)
  agents/
    __init__.py          # imports every submodule; re-exports public names
    common.py            # _fill
    extract.py           # ExtractStage, ExtractReply, EXTRACT_PROMPT
    skill_gap.py         # SkillGapStage, SkillGapReply, SKILL_GAP_PROMPT
    score.py             # ScoreStage, ScoreReply, SCORE_PROMPT
```

Each stage module carries its stage class, its reply schema (agents), and its prompt constant (agents) — everything needed to understand or clone that one stage.

## Compatibility Requirements (binding)

1. **Import paths must not change for consumers.** These imports work today and must keep working verbatim:
   - `from job_pipeline.stages.rules import make_fuzzy_key` (used by `job_pipeline/seeders/existing_vault.py:10`)
   - `from job_pipeline.stages.rules import DedupStage, HardFilterStage, FuzzyDedupStage, LocationStage, SalaryStage, make_fuzzy_key` (tests)
   - `from job_pipeline.stages.agents import ExtractStage, SkillGapStage, ScoreStage` (tests)
   - Prompt constants and reply models (`EXTRACT_PROMPT`, `ExtractReply`, etc.) importable from `job_pipeline.stages.agents`.

   Each package `__init__.py` achieves this by importing its submodules and re-exporting the public names via explicit imports + `__all__`.

2. **Registration side-effects must still fire.** `job_pipeline/core/pipeline.py:17-18` does `import job_pipeline.stages.rules` / `import job_pipeline.stages.agents` for registry population. Importing the package must import every stage submodule (the `__init__.py` imports guarantee this).

3. **`_fill` stays importable as `job_pipeline.stages.agents._fill`** — it is underscore-private but tests may reference it; re-export it from the package `__init__.py`.

4. **Zero test edits.** The full suite (`pytest`, 68 tests, 1 integration deselected) must pass unchanged. If a test needs editing, the refactor is wrong.

## Non-Goals

- No renaming of stage classes, registry names, or config keys.
- No splitting of `publish.py` (single stage already).
- No docstring rewrites beyond a one-line module docstring per new file.
- No `stages/__init__.py` re-exports (nothing imports from it today).

## Acceptance

- `pytest` → 68 passed, 1 deselected, zero test-file diffs.
- `git log` shows old files removed, packages added (use `git mv`-friendly commits where practical so blame survives).
- README "extending" section updated to point at one stage file as the copy-me template (one-paragraph edit).
