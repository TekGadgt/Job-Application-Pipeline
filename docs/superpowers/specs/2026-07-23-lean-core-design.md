# Lean Core Re-cut — Design Spec

**Date:** 2026-07-23
**Status:** Approved for planning
**Motivation:** Usage review (2026-07-23): the pipeline's filtering gates are over-engineered relative to how Ryan actually uses it. The location gate rejected a viable commutable role (Colonial Williamsburg); he is open to remote *and* relocation, so metro gating is prohibitive by design, not just by bug. Salary floors mis-handle foreign currencies and the fix (comp normalization) is machinery serving a gate that shouldn't exist. `must_have_skills`/`nice_to_have` turned out to be dead config — parsed, consumed nowhere. The philosophy shift: **filter almost nothing deterministically; let the fit score carry judgment; surface everything in the note.** Deterministic gates remain only where they save agent tokens on listings that would never be pursued (`hard_filter`) or are true duplicates (URL dedup).

## Goal

A lean default pipeline:

```
[dedup, hard_filter, extract, dedup_fuzzy, skill_gap, score, publish]
```

with `dedup_fuzzy` demoted to record-only, the location/salary gate modules deleted, and dead profile config removed. More intense steps stay available as opt-ins (`score_floor`) or shelved specs.

## Components

### 1. Delete the location and salary gates

- Delete `stages/rules/location.py`, `stages/rules/salary.py`, their registry entries, and their tests.
- `HOURS_PER_YEAR` in `stages/rules/common.py` loses its only consumer — delete it too.
- Default `stages:` list in `pipeline.example.yaml`, Ryan's `pipeline.yaml`, and the README updated to the lean list.
- **Explicitly retained:** `hard_filter` (free, pre-agent, saves tokens — confirmed keeper), `dedup` (URL-level, the only hard dedup), and `score_floor` (optional opt-in stage, not in the default list; it gates on *fit*, which is the one judgment we trust).

### 2. `dedup_fuzzy` becomes record-only

- Still computes `job.fuzzy_key` (the company+role+location secondary ID) and it is still written to the seen index on publish — the identity data survives.
- On a fuzzy-key hit (current or legacy), **no rejection**: trace `possible duplicate: <key>` and continue. URL/ID is the only dedup that rejects.
- `produces` drops `rejected`. The stage never rejects.
- This also dissolves the known false-collision: two genuinely distinct roles with the same company+title+location previously killed the second one. Surfacing `possible duplicate` in the note frontmatter is Batch B's concern (alongside the new `location` and comp keys), not this spec's.

### 3. Profile cleanup (`config.py`)

- Remove from `Profile`: `locations` (+ the `LocationRules` model), `salary_floor`, `salary_not_listed`, `must_have_skills`, `nice_to_have`. Pydantic ignores unknown frontmatter keys by default, so existing profile files load unchanged — stale keys are simply inert. README documents the removals.
- Remove `keep_rejects` from `OutputConfig`, `pipeline.example.yaml`, and the README (same inert-key behavior). This fast-forwards the retirement the observability spec (Batch F) already decided; F's spec item 5 becomes a no-op.
- `score_floor` stays in `Profile`. `blocklist` stays (feeds `hard_filter`).
- `profile.example.md` and Ryan's `profile.md` frontmatter trimmed to: `score_floor` (commented), `blocklist`. Location/salary preferences belong in the prose body where the score agent weighs them (e.g. "open to remote and relocation" — the score agent should know it, not a gate).

### 4. Shelved specs

Mark Status "Shelved (2026-07-23 lean re-cut)" on: `2026-07-16-location-normalization-design.md`, `2026-07-18-comp-normalization-design.md`. Both were gate-serving machinery; they remain on file should gating return. Roadmap moves batches B2, C, D, G, H to a Shelved section (C's fetcher seam may be pulled piecemeal into Batch E when scrape needs it).

## Testing (no network, no tokens)

- `dedup_fuzzy`: seeded fuzzy hit → job proceeds with `possible duplicate` trace; legacy-key hit likewise; key still computed and recorded.
- Registry: `location`/`salary` no longer resolvable; lean default stage list builds and runs end-to-end under MockRunner.
- Config: a profile file still containing `locations:`/`salary_floor:`/`must_have_skills:` loads without error and without those fields; same for `keep_rejects` in pipeline yaml.
- Existing tests for deleted modules removed, not skipped.

## Non-Goals

- No frontmatter changes (location/comp/possible-duplicate keys land with Batch B's comp-in-notes rebase).
- No new sources or discovery (Batch E), no run history (Batch F), no VEC enrichment (last).
- No removal of the `location`-string extraction or `fuzzy_key` computation — the *data* stays; only the *gating* goes.
