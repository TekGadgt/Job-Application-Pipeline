# Location-Aware Fuzzy Dedup — Design Spec

**Date:** 2026-07-09
**Status:** Approved for planning
**Motivation:** Real incident (2026-07-09): LiveKit lists "Forward Deployed Engineer" independently per location under different Ashby job ids. The fuzzy key is `normalize(company)|normalize(title)`, so the second location was rejected as `duplicate role: livekit|forwarddeployedengineer` — a distinct, applicable posting lost. Same role + different location must be treated as different jobs.

## Goal

Fuzzy dedup keys become location-aware: `company|title|location`. Cross-URL reposts of the same role **in the same location** still dedup; the same role in a different location passes. Legacy 2-part keys already in the seen index keep their full blocking power (no migration, no re-surfacing of old decisions).

## Design

### 1. Key format (stages/rules/common.py)

```python
def make_fuzzy_key(company: str, title: str, location: str = "") -> str:
    # normalize each part with the existing [^a-z0-9] strip
    return f"{norm(company)}|{norm(title)}|{norm(location)}"
```

- `location=""` default keeps every existing call site valid during the transition and is the explicit form for location-less contexts (seeder, import).
- Emptiness guard generalizes: a key is "no key" (never marked, never matched) when **company and title are both empty** — replacing today's literal `!= "|"` check in `dedup_fuzzy` and the seeder. Empty location alone is fine: two location-less listings of the same role match each other (`acme|engineer|` == `acme|engineer|`), preserving today's behavior for feeds that don't carry location.

### 2. Matching with legacy keys (stages/rules/dedup_fuzzy.py)

`FuzzyDedupStage.run` computes the 3-part key (using `job.location`, available post-extract — StageSpec `requires` gains `"location"`) and checks **both** forms:

```python
job.fuzzy_key = make_fuzzy_key(job.company, job.title, job.location)
legacy = make_fuzzy_key(job.company, job.title)          # "company|title|"  → strip to 2-part form
if self.seen.has_fuzzy(job.fuzzy_key) or self.seen.has_fuzzy(legacy_2part):
    job.mark_rejected(...)
```

Where `legacy_2part` is the pre-change format `f"{norm(company)}|{norm(title)}"` (exactly what existing rows hold). Semantics: **rows written before this change block the role in all locations** — they were terminal decisions made under the old rules and stay honored; rows written after are location-scoped. No schema change, no data migration, `StateStore.has_fuzzy` untouched (two calls, not a new API).

The plan implements `legacy_2part` via a small private helper next to `make_fuzzy_key` (not string-slicing the 3-part key inline).

### 3. Writers of fuzzy keys

- `dedup_fuzzy` sets `job.fuzzy_key` to the 3-part form; `run_pipeline`'s terminal `seen.mark` needs no change.
- **Seeder** (`existing_vault.py`): gains optional `location_field: str = ""` config kwarg. When set and the note has the field → 3-part key; otherwise → legacy 2-part key (deliberate: an old tracker without locations should block the role everywhere, matching legacy semantics).
- **Vault-import spec** (2026-07-03): same rule via its `fields:` map — when `location` is mapped and present → 3-part, else 2-part. One-line amendment to that spec's step 5 is included in this spec's plan (edit the spec doc in the same commit that implements this, keeping docs truthful).

### 4. Trade-off (documented in README's dedup paragraph)

Location strings are free text from the extract agent; normalization collapses punctuation/spacing only, so `Remote` vs `Remote (US)` → `remote` vs `remoteus` are *different* keys and a true duplicate may slip through as a second note. This is the correct direction to err: a duplicate note costs a few seconds of triage; a falsely-deduped distinct posting is an application never made. No location canonicalization (metro synonym tables, remote-flag parsing) — YAGNI until it demonstrably hurts.

## Coordination

- **Reprocess flag** (2026-07-03): unchanged; its "fuzzy dedup may still catch a role seen via another URL" note now applies per-location for new rows.
- **Store backends** (2026-07-03): `has_fuzzy` signature unchanged; no interaction.
- **Observability** (2026-07-03): reject reasons will show the 3-part key; no change needed.
- Land order vs other specs: independent; touches `common.py`/`dedup_fuzzy.py`/`existing_vault.py` only.

## Testing (no network, no tokens)

- `make_fuzzy_key`: 3-part composition; empty location; normalization per part.
- `dedup_fuzzy`: same company+title, different locations → second job passes; same all three (different URLs) → rejected; legacy 2-part row in a seeded index blocks the role for any location; company+title both empty → no mark, no match (guard).
- Seeder: with `location_field` and field present → 3-part; without → legacy 2-part; existing seeder tests unchanged otherwise.
- e2e (MockRunner): repost-different-location scenario — two jobs, same role, locations A/B, both publish; then location-A repost under a third URL rejects.

## Non-Goals

- No location canonicalization/synonym mapping.
- No retroactive rewrite of existing seen rows (legacy compatibility path instead).
- No per-profile "treat these metros as one" config.
- No change to URL-hash dedup (primary key semantics untouched).
