# Source Module Split — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Scope:** Mechanical refactor, sibling of the stage package refactor (2026-07-02, shipped): one registered source per module, so every pluggable kind (stages, sources, seeders) follows the same predictable copy-me layout.

## Goal

`job_pipeline/sources/feeds.py` (currently `rss` + `greenhouse` + `lever` in one file) splits into one module per source. End state:

```
job_pipeline/sources/
  __init__.py        # imports every source module (registration side-effect) — NEW behavior
  base.py            # Source protocol, http_get_text/json, HintedSource (unchanged)
  rss.py             # RssSource
  greenhouse.py      # GreenhouseSource
  lever.py           # LeverSource
  manual.py          # ManualSource (already one-per-file; unchanged)
```

Each module carries exactly its class, verbatim-moved — no logic edits.

## One deliberate difference from the stage refactor (binding)

**No `feeds.py` compatibility shim.** The stage refactor's gate was byte-for-byte import compatibility because external-facing consumers (seeder, tests) imported from those paths. Here the only importers of `job_pipeline.sources.feeds` are our own test file and `core/pipeline.py`'s side-effect imports — and a shim would permanently contradict the refactor's whole point (a fork author browsing `sources/` should see one obvious pattern, not a legacy aggregator module). Clean break:

- `tests/test_sources.py` updates its one import line to the three new modules — the **only** test edit permitted; all test bodies, fixtures, and assertions are untouched.
- `job_pipeline/core/pipeline.py` replaces its two source side-effect imports (`job_pipeline.sources.manual`, `job_pipeline.sources.feeds`) with a single `import job_pipeline.sources` — see below.

## `sources/__init__.py` becomes the registration aggregator (binding)

Mirroring `stages/rules/__init__.py`: the package `__init__` imports every source module so `import job_pipeline.sources` fires all `@register_source` decorators, and re-exports the public names (`Source`, `HintedSource`, `http_get_text`, `http_get_json`, `RssSource`, `GreenhouseSource`, `LeverSource`, `ManualSource`) with `__all__`. This is also the convention a fork follows: *add your module, add one import line to `__init__.py`, done* — same muscle memory as adding a stage.

Existing deep imports (`from job_pipeline.sources.base import HintedSource`, `from job_pipeline.sources.manual import ManualSource` in cli.py/pipeline.py/tests) keep working unchanged — modules keep their paths; only `feeds` disappears.

## Compatibility Requirements

- Registry names (`rss`, `greenhouse`, `lever`, `manual`) and all class behavior unchanged.
- The `self._get` monkeypatch seam preserved verbatim in each moved class.
- Full suite passes with only the single permitted import-line edit in `tests/test_sources.py`.
- README "Pluggable sources" section gains the copy-me pointer, mirroring the stages paragraph: copy `job_pipeline/sources/greenhouse.py` as the template (it shows fetch + field mapping in ~20 lines), register with `@register_source("your_name")`, add an import line to `sources/__init__.py`, reference it by `type:` in `config/pipeline.yaml`.

## Coordination

- **Scrape-source spec** (2026-07-02) and **js-fallback-fetcher spec** (2026-07-03) both add modules under `sources/` — they land naturally in this layout (`scrape.py`, `fetch.py`); neither needs amendment, but this split should land **before** them so they're born into the final structure.
- No interaction with runners/observability/UI specs.

## Testing

No new tests. The gate is the existing suite green with only the one import-line diff under `tests/`, plus the whole-plan smoke check: `python -c "import job_pipeline.sources; from job_pipeline.core.registry import get_source; [get_source(k) for k in ('rss','greenhouse','lever','manual')]"`.

## Non-Goals

- No behavior/docstring changes beyond one-line module docstrings.
- No splitting of `base.py` (protocol + shared HTTP helpers + HintedSource is a cohesive unit at this size).
- No seeder split (`existing_vault.py` is already one-per-file; the pattern already holds there).
