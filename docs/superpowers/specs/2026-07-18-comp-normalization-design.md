# Compensation Normalization — Design Spec

**Date:** 2026-07-18
**Status:** Approved for planning
**Motivation:** The salary stage ignores `comp_currency` entirely: a £90,000 listing compares `90000 < 100000` against a USD floor and is rejected, even though it's ~$120k. This is a live correctness bug, not just a gap — extract already emits `comp_currency`, and nothing reads it. Second of the modular pre-gate normalizer family established by `2026-07-16-location-normalization-design.md`: each normalizer sits immediately before the filter gate it feeds.

## Goal

1. Comp listed in a foreign currency is converted to the profile's floor currency before the salary gate compares it.
2. One knob expresses intent: a single `salary_floor` in a default currency, with conversion — not per-currency floors. (Per-currency floors are recoverable anyway: `fx_rates` overrides are per-currency, so tuning a rate is effectively a per-currency floor, e.g. to bake in cost-of-living judgment.)
3. The salary stage becomes a pure compare; annualization and conversion both live in the normalizer.

## Design decision

**Static rate table + profile override** (chosen): approximate rates for the common currencies baked into the code with the as-of date documented, `fx_rates:` in the profile merged over them. Deterministic, free, testable; a coarse floor tolerates slow drift, and the override is the escape hatch when it doesn't.

Rejected: live FX API (adds network and failure modes to a deliberately deterministic stage family); profile-only rates (manual upkeep, dead ends on any unlisted currency); per-currency floors (defining a GBP floor *is* doing the conversion by hand once — it drifts identically while expressing intent less directly, and fails on unlisted currencies).

## Components

### 1. Currency helpers (`job_pipeline/normalize.py`)

The shared normalize module (created by the location spec) grows:

- `normalize_currency(text: str | None) -> str | None` — symbols/aliases → ISO code (`$`→`USD`, `£`→`GBP`, `€`→`EUR`, `¥`→`JPY`, case-insensitive codes passed through upper-cased). Unrecognized input returns it cleaned/upper-cased (fail open — the rate lookup decides convertibility).
- `FX_TO_USD: dict[str, float]` — rates for the common set: USD (1.0), EUR, GBP, JPY, CAD, AUD, CHF. Values documented with an as-of date; precision is not the point, the floor is coarse.
- `annualize(amount: int, period: str | None) -> int` — hourly→annual via `HOURS_PER_YEAR` (moves from the salary stage's inline logic; `common.py`'s constant is the source of truth), any other/absent period treated as annual.

### 2. Profile additions (`config.py`)

- `salary_currency: str = "USD"` — the currency `salary_floor` is denominated in.
- `fx_rates: dict[str, float] = {}` — floor-currency units per 1 unit of listing currency; an overridden currency uses this rate directly (no cross-rate). Keys normalized through `normalize_currency` at load.

Built-in rates are USD-denominated (`FX_TO_USD`); a non-USD floor currency converts via USD cross-rate from that one flat map. `fx_rates` entries, being floor-currency-denominated, bypass the cross-rate — with the default USD floor the two denominations coincide.

### 3. `normalize_comp` stage (`job_pipeline/stages/rules/normalize_comp.py`)

- `StageSpec("normalize_comp", "annualize and convert comp to the floor currency", requires=["comp_max", "comp_currency", "comp_period"], produces=["comp_comparable"], kind="deterministic", cost_tier="free")`.
- Produces a **derived** field `comp_comparable: int | None` (new field on `core/job.py`'s `Job`, default `None`): `comp_max`, annualized, converted to `salary_currency`. It does **not** overwrite `comp_min`/`comp_max`/`comp_currency`/`comp_period` — comp-in-notes (Batch B) renders the originals, and conversion is lossy.
- Null/empty `comp_currency` → assumed to be the floor currency (most US listings never state one).
- Unknown currency (no rate after merge) → `comp_comparable = None`, trace warning naming the currency.
- `comp_max is None` → `comp_comparable = None`, trace `no comp listed`.
- Never rejects.

### 4. Salary stage becomes a pure compare (`stages/rules/salary.py`)

`requires=["comp_comparable"]`. Logic: floor unset → pass; `comp_comparable is None` → the existing `salary_not_listed` policy (unknown currency and unlisted comp are the same epistemic state: comp unknown in floor terms); otherwise `comp_comparable >= floor`. Reject reason includes both sides, e.g. `below floor (95000 < 100000 USD)`. The inline `HOURS_PER_YEAR` annualization is deleted here (moved to the normalizer).

### 5. Stage ordering + example config

Default stage list becomes:

```
[dedup, hard_filter, extract, normalize_location, dedup_fuzzy, location, normalize_comp, salary, skill_gap, score, publish]
```

(`normalize_comp` immediately before its gate, per the family pattern.) `pipeline.example.yaml` and README updated. `profile.example.md` gains commented-out lines:

```yaml
# salary_currency: USD    # currency salary_floor is denominated in
# fx_rates: {GBP: 1.27, EUR: 1.08}   # override built-in rates (floor-currency per 1 unit)
```

## Testing (no network, no tokens)

- `normalize_currency`: symbol map, lowercase codes, unknown passthrough, None → None.
- `annualize`: hourly × HOURS_PER_YEAR; annual/None unchanged.
- Stage: GBP `comp_max` converts using the built-in rate; profile `fx_rates` override wins over built-in; null currency assumed floor currency (comp_comparable == annualized comp_max); unknown currency → None + trace warning; hourly comp annualized then converted; comp_max None → None.
- Salary stage: compares `comp_comparable`; None routed through `salary_not_listed` both ways (keep/reject); reject reason names both sides and currency.
- Integration: £90k listing with a $100k floor and GBP rate 1.27 **passes** (the motivating case); same listing with `fx_rates: {GBP: 1.0}` rejects.
- Non-USD floor currency: EUR floor converts a GBP listing via USD cross-rate.

## Non-Goals

- No live FX fetching, no rate caching, no cost-of-living adjustment (the `fx_rates` override is the manual lever for that).
- No changes to extract's comp fields or comp-in-notes rendering — originals are preserved untouched.
- `comp_min` is not normalized (nothing gates on it; revisit if something does).
