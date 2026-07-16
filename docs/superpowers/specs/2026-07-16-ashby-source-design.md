# Ashby Source — Design Spec

**Date:** 2026-07-16
**Status:** Approved for planning
**Scope:** One new pull source (`type: ashby`) for Ashby-hosted job boards, joining Batch E (intake expansion). Ashby is prominent among modern companies and startups and exposes a clean public posting API — this is a Greenhouse-clone-sized module. This spec also records a deliberate deferral: **no dedicated UltiPro source** (see Non-Goals).

## Goal

`config/pipeline.yaml` accepts:

```yaml
sources:
  - {type: ashby, board: examplecompany}   # slug from jobs.ashbyhq.com/<slug>
```

and every listed posting on that board flows into the pipeline with url, title, location pre-filled and a `raw_text` rich enough for the extract agent to parse description and compensation.

## API (verified live 2026-07-16 against the `ashby` board)

One GET, no auth, no pagination — the full board comes back in one response:

```
GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
→ {"jobs": [...], "apiVersion": ...}
```

Per-job fields used: `jobUrl`, `title`, `location` (string), `isRemote` (bool), `isListed` (bool), `secondaryLocations` (list of `{location, address}`), `descriptionPlain` (clean text, HTML sibling ignored), `compensation.compensationTierSummary` (human-readable string, e.g. `€76K – €185K • Offers Equity • Offers Bonus`).

## Design

### `job_pipeline/sources/ashby.py` (new module)

`AshbySource`, `@register_source("ashby")`, constructor `(board: str)`, using the shared `http_get_json` with the same `self._get = http_get_json` monkeypatch seam as greenhouse/lever. Per job in `data.get("jobs", [])`:

- **Skip** jobs where `isListed` is falsy.
- `url` ← `jobUrl`; pre-fill `j.title` ← `title`, `j.location` ← `location` **verbatim** (no remote rewriting at the source — the location rule stage and extract agent own remote semantics).
- `raw_text` composition, in order, newline-joined:
  1. title
  2. a location line: `Location: {location}`, with ` (Remote)` appended when `isRemote`, and ` — also: {loc1}, {loc2}, …` appended when `secondaryLocations` is non-empty (each entry's `location` string).
  3. `Compensation: {compensationTierSummary}` — only when the summary is present and non-empty.
  4. `descriptionPlain`
- All field access via `.get` with `""`/`{}`/`[]` defaults — a sparse job never raises.
- `on_terminal` is a no-op, matching the other pull sources.

Compensation parsing stays with the extract agent (extract owns parsing; sources ship strings). Ashby's structured `compensationTiers` are deliberately **not** mapped onto `comp_min`/`comp_max` at the source — multiple tiers per posting don't fit the flat fields, and a second comp parser would duplicate extract's job.

### Error handling

Same posture as greenhouse/lever: HTTP errors propagate from `http_get_json`; the runner's existing per-source failure handling applies. No retries, no pagination, no rate limiting.

## Coordination (binding)

- **Batch E, post-split layout.** Lands in Batch E alongside scrape + js-fallback, after the source-module-split (Batch C) has merged. `ashby.py` is born as its own module per the split spec's convention: add the module, add one import line + `__all__` entry (`AshbySource`) to `sources/__init__.py`, done. It must **not** be added to `feeds.py`.
- `config/pipeline.example.yaml` gains a commented example line alongside greenhouse/lever.
- README "Pluggable sources" section: add `ashby` to the list of built-in source types.
- `docs/ROADMAP.md` Batch E gains this spec's bullet (edited in the same commit as this spec).

## Testing (fixture-driven, no network, `test_sources.py` style)

A captured two-job fixture (trimmed from the live probe) drives:

- url/title/location mapping asserted per job.
- `raw_text` composition: comp summary line present when compensation exists; location line carries `(Remote)` and secondary locations when the fixture says so.
- A job with `isListed: false` is skipped.
- A job with no `compensation` (or empty summary) renders `raw_text` with no `Compensation:` line.
- The `self._get` seam is monkeypatched exactly as in the greenhouse/lever tests.

## Non-Goals

- **No UltiPro source.** UltiPro/UKG Pro appears less often, and its board API is a different animal (POST search endpoint, per-tenant ID + board GUID, extra request per job for descriptions). Decision: cover UltiPro-hosted companies via Batch E's `type: scrape` careers-page source (with the js-fallback fetcher for its JS-heavy pages). Revisit a dedicated source only if scrape quality proves insufficient on real UltiPro boards.
- No structured comp mapping at the source (extract owns parsing).
- No `descriptionHtml` conversion (`descriptionPlain` is already clean).
- No per-job detail fetches, pagination, or auth — the board endpoint returns everything.
- No department/team/employmentType mapping; they're absent from `Job` and the extract agent recovers what matters from raw_text.
