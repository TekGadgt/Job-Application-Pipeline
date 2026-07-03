# Compensation in Published Notes — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Scope:** Tiny. The extract agent already parses numeric comp (`comp_min`/`comp_max`/`comp_currency`/`comp_period`) and the salary stage validates against it — but none of it reaches the published note. Good information, already paid for; surface it.

## Goal

Every published note carries the parsed compensation twice: as queryable frontmatter (Dataview can sort/filter jobs by pay) and as a human-readable body line.

## Design

### 1. Frontmatter (store/obsidian.py)

Four keys inserted **immediately after `score`** in the existing mapping (order is stable and binding — `sort_keys=False`):

```yaml
comp_min: 150000        # null when not listed
comp_max: 180000
comp_currency: USD      # null when not listed
comp_period: annual     # annual | hourly | null
```

Keys are **always present** (null when absent) so every note has an identical frontmatter schema — Dataview queries never need existence guards.

### 2. Body section

A `## Compensation` section between `## Fit` and `## Skill gap`, rendered by a pure helper `format_comp(job) -> str` in `store/obsidian.py`:

- Range: `$150,000–$180,000 USD (annual)`
- Single value (only `comp_max` or equal min/max): `$150,000 USD (annual)`
- Hourly: `$35–$40 USD/hr (≈ $72,800–$83,200 annualized)` — annualized at the same `HOURS_PER_YEAR = 2080` the salary stage uses (import it from `job_pipeline.stages.rules`; one constant, one truth).
- Not listed: `Not listed` — followed on the same line by ` — listed text: "<comp_text>"` whenever `comp_text` is non-empty but numbers weren't parsed (the verbatim string is the only signal in that case).
- When numbers exist AND `comp_text` differs meaningfully, append ` (listed as "<comp_text>")` for provenance.
- Currency: prefix `$` only for USD/absent-currency; otherwise `150,000–180,000 EUR (annual)` (no symbol lookup table — YAGNI).
- Thousands separators via `f"{n:,}"`.

## Compatibility

- Published-note format changes (new keys + section): the existing publish tests update to the new golden content — that's the feature, not a regression. Skip-on-edit protection is untouched: previously published, user-advanced notes are never rewritten (except `--force`).
- No changes to extract, salary, Job, or config.
- The resume-match spec (2026-07-03) also adds note content, but conditionally; comp keys/section are **unconditional**. Binding combined order — frontmatter: `..., score, comp_min, comp_max, comp_currency, comp_period, status, job_id` (resume keys, when present, after `job_id`); body: Fit, Compensation, Resume Match (when present), Skill gap, Description. Whichever spec lands second rebases golden-note test expectations mechanically.

## Testing (no network, no tokens)

- `format_comp` unit tests: range/single/hourly-annualized/not-listed/comp_text-only/non-USD/thousands-separator cases.
- Publish: frontmatter contains the four keys in the bound position with correct null handling; body contains the section in the bound position; a no-comp job renders `Not listed`.
- Existing e2e golden assertions updated once.

## Non-Goals

- No currency conversion or symbol tables beyond `$` for USD.
- No comp keys in the seen index or run history.
- No re-render of previously published notes (they update only if the same job is force-republished).
