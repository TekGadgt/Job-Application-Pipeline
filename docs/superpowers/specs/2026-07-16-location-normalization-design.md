# Location Normalization — Design Spec

**Date:** 2026-07-16
**Status:** Approved for planning
**Motivation:** Real incident: the Colonial Williamsburg "Software Engineer II or III" posting extracted `location: "Williamsburg, Virginia"` and was rejected by the location stage even after the user added `"Williamsburg, VA"` to `allowed_metros` — the substring match compares literal strings, so `va` never matches `virginia`. The same abbreviation-vs-full-name mismatch is latent for every metro in the profile; any board that spells out the state name slips past. The stopgap (hand-duplicating every metro in both spellings) doesn't scale and invites typos.

## Goal

1. Extracted locations and profile metros are both canonicalized through one shared function, so the location gate compares canonical-to-canonical.
2. Normalization is a deterministic, free, unit-testable stage — the first of a modular family: each normalizer sits immediately before the filter gate it feeds (location normalization before the location filter; a future wage normalizer would sit before the salary filter). Combined where it matters, independent otherwise.
3. The profile's duplicated metro list collapses back to one entry per metro.

## Design decision

**Approach A — pure deterministic normalizer** (chosen): no LLM, a state-name table and noise-stripping rules.

**Approach C — escalation path** (deferred, noted for the record): if real-world formats defeat the deterministic rules (e.g. `US-VA-Williamsburg`, `Greater Richmond Area`), upgrade by having extract emit structured fields (`location_city`, `location_region`, `location_country`, `location_remote`) and let this same stage canonicalize the region and rebuild the string. The stage boundary is identical either way — only the parsing inside changes. LLM canonicalization inside extract itself was rejected: it breaks the modular gate pattern, isn't deterministic, and leaves nothing to normalize the profile side.

## Components

### 1. Canonicalization helper (`job_pipeline/normalize.py`)

New top-level module (importable by both config and stages without a config→stages dependency):

- `normalize_location(text: str) -> str` — the one shared entry point.
- `US_STATES: dict[str, str]` — full state name → USPS abbreviation (50 states + DC + territories).

Rules, applied in order to a lowercased working copy:

1. Collapse whitespace; strip surrounding punctuation.
2. Strip country suffixes: trailing `, united states`, `, usa`, `, us`.
3. Strip work-mode qualifiers as standalone tokens: `hybrid`, `onsite`, `on-site`, `in-office` (parenthesized or dash-separated forms included). `remote` is **not** stripped — it is signal, not noise.
4. Split on multi-location delimiters (`/`, `;`, `|`), normalize each segment, rejoin with ` / `.
5. Per segment: if it matches `city, <full state name>` or `city, <abbrev>`, emit `City, ST` (title-case city, upper-case USPS abbreviation). A remote-only segment emits `Remote`. Remote + city emits `Remote — City, ST`.
6. **Fail open:** a segment that doesn't parse passes through cleaned but otherwise unchanged. Normalization must never destroy information the location gate could still substring-match.

The output contract preserves the location stage's existing semantics: `"remote" in loc.lower()` still detects remote, and canonical metros substring-match canonical locations.

### 2. `normalize_location` stage (`job_pipeline/stages/rules/normalize_location.py`)

- `StageSpec("normalize_location", "canonicalize the extracted location string", requires=["location"], produces=["location"], kind="deterministic", cost_tier="free")`.
- `run()` replaces `job.location` with `normalize_location(job.location)` and traces the change: `'Williamsburg, Virginia' -> 'Williamsburg, VA'` (or `unchanged`). Empty location passes through untouched (the observability spec's errored guard owns that case).
- Never rejects.

### 3. Stage ordering (config, example yaml, README)

Default stage list becomes:

```
[dedup, hard_filter, extract, normalize_location, dedup_fuzzy, location, salary, skill_gap, score, publish]
```

`normalize_location` must precede `dedup_fuzzy`, not just `location`: the fuzzy key bakes in the location string, so keys must be built from canonical locations or cross-source dedup reintroduces the same mismatch.

### 4. Profile-side normalization (`config.py`)

`Profile` load passes each `allowed_metros` entry through the same `normalize_location`. An entry that fails to parse (the detectable case is an unknown state name; city-name typos are inherently undetectable without a gazetteer) logs a load-time warning naming the entry, instead of silently never matching. The profile's duplicated metro list is collapsed back to single canonical entries as part of this spec.

### 5. `relocation` flag (`config.py`, `stages/rules/location.py`, example profile)

*Added 2026-07-18.* `LocationRules` gains `relocation: bool = False`. When true, the location gate passes every job — overriding both `allowed_metros` and the remote check — with trace `passed (relocation: all locations accepted)`. `normalize_location` still runs regardless: canonical locations still feed fuzzy dedup and notes. `profile.example.md` gets a commented-out `# relocation: true` line under `locations:`.

### 6. Fuzzy-key drift (accepted, documented)

Canonical locations change future fuzzy keys, so existing seen-index rows keyed on raw locations won't match their canonical successors — a cross-source duplicate of an already-seen role could slip through once. With ~17 rows in the index, this one-time drift is accepted; no migration. (URL-level dedup is unaffected.)

## Testing (no network, no tokens)

- Table-driven unit tests for `normalize_location`: `Williamsburg, Virginia → Williamsburg, VA`; `Richmond, VA` idempotent; `New York, New York → New York, NY`; trailing `, United States` stripped; `Hybrid - Williamsburg, VA → Williamsburg, VA`; `Remote` / `Fully Remote (US) → Remote`; `Remote — Richmond, VA` remote+city form; `Richmond, VA / Seattle, WA` multi-location; `Greater Richmond Area` fail-open passthrough; empty string passthrough.
- Stage test: `job.location` replaced, trace records old → new; empty location untouched.
- Profile test: metros normalized at load; unknown-state entry produces a warning.
- Relocation test: `relocation: true` passes a job whose location matches no metro and isn't remote; `relocation: false` (default) preserves current behavior.
- Integration (stage list with MockRunner): a job extracting `"Williamsburg, Virginia"` against a profile listing `"Williamsburg, VA"` passes the location gate; its fuzzy key is built from the canonical form.

## Non-Goals / Future Work

- **No geocoding or radius matching** — considered and dropped for now.
- **No international canonicalization** beyond fail-open passthrough.
- **Approach C** (structured location fields from extract) is the named escalation path, not part of this spec.
- **Fuzzy-key collisions between genuinely distinct roles** (observed: two different "Senior Software Engineer" reqs, same company, same location → second falsely rejected as duplicate) is out of scope but recorded here as a future-spec seed. Candidate discriminators, in rough order of promise: a requisition/job ID field in extract (most ATSes expose one — Greenhouse/Lever/Ashby/UltiPro all carry it in the URL or posting); the comp range (distinct reqs usually have distinct bands); or demoting a fuzzy-key hit to "suspected duplicate" confirmed by a cheap description-similarity check before rejecting.
