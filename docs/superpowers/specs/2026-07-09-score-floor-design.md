# Score Floor Stage — Design Spec

**Date:** 2026-07-09
**Status:** Approved for planning
**Scope:** Tiny. One deterministic stage between `score` and `publish`: jobs scoring below a configured floor are rejected instead of landing in the vault. Zero tokens (the spend already happened at `score` — this filters the output, it can't save the opus call).

## Config Syntax (binding)

Profile frontmatter (personal preference, alongside `salary_floor`):

```yaml
score_floor: 60        # optional; absent/null = no floor, today's behavior
```

pipeline.yaml stage list (optional stage, canonical position):

```yaml
stages: [dedup, hard_filter, extract, dedup_fuzzy, location, salary, skill_gap, score, score_floor, publish]
```

Example configs ship with `score_floor` present in the stage list **commented out** and a commented `score_floor: 60` in `profile.example.md`.

## Design

### Stage (stages/rules/score_floor.py)

`ScoreFloorStage`, `@register_stage("score_floor")` — a rule stage (deterministic, `cost_tier="free"`), StageSpec: purpose "reject jobs scoring below the profile's floor", requires `["score"]`, produces `["rejected"]`.

`Profile` gains `score_floor: int | None = None` (config.py). Constructor `(profile)`, mirroring `SalaryStage`; `from_context` → `cls(ctx.profile)` when the stage-context spec lands.

`run` semantics (mirrors `SalaryStage`'s shape):

- `floor is None` → pass, trace `("score_floor", "no floor configured")`.
- `job.score is None` → pass, trace `("score_floor", "no score present; passed")` — the stage doesn't punish a misordered config (listed before `score`, or `score` not in the list); it filters only when there's a score to filter.
- `job.score >= floor` → pass, trace `("score_floor", f"passed ({job.score} >= {floor})")`.
- else → `job.mark_rejected("score_floor", f"score {job.score} below floor {floor}")`.

### Consequences to document (README, two sentences)

A score-floor rejection is **terminal**: the URL (and 3-part fuzzy key, once location-aware dedup lands) is marked seen, so the same posting won't be re-scored next run. That's the point — but raising your floor later doesn't resurrect past rejects (use `--reprocess` per URL when it lands), and reject reasons become visible via the observability spec's `why` command; until then they appear in the run's log line only.

## Coordination

- **Stage-context spec** (2026-07-03): adds its two-line `from_context` like every other rule stage — covered by that plan's uniform loop, no amendment needed.
- **Observability / reprocess** (2026-07-03): no interaction beyond the README sentences above.
- Independent of everything else in the backlog; lands anytime.

## Testing (no network, no tokens)

- Unit: floor None → pass; score None → pass with trace; score == floor → pass (boundary is inclusive-keep); score below → rejected with stage `score_floor` and both numbers in the reason.
- Wiring: stage constructible from the registry via `build_stages` with `profile`.
- e2e (MockRunner): score reply below floor → `summary.rejected` counts it, no note written, URL marked seen; floor absent → identical run publishes.

## Non-Goals

- No pre-score prediction/short-circuit (the floor filters output; saving agent spend on low-fit jobs is the skill-gap/score prompts' job).
- No per-source or per-stage-list floors, no soft-floor "publish but flag" mode (keep_rejects-style vault clutter was already rejected once; the observability trail is where near-misses live).
- No re-evaluation of previously rejected jobs on floor changes.
