# JSON-LD JobPosting Extraction — Design Spec

**Date:** 2026-07-25
**Status:** Approved for planning
**Batch:** E4, ordered **before** `2026-07-03-js-fallback-fetcher` (it reduces how often the browser is needed)
**Related:** `2026-07-02-scrape-source`, `2026-07-03-js-fallback-fetcher`, `docs/JobBoardDetection.md`

**Motivation:** Verified 2026-07-25 against `https://githubinc.jibeapply.com/jobs/5623` (GitHub's public iCIMS/Jibe board, used because their own `careers-githubinc.icims.com` tenant IP-gates the sitemap with a 403):

| | size | ≈ tokens |
|---|---|---|
| Raw HTML — what `extract` receives today | 576,451 chars | **~144,000** |
| Visible text after stripping `<script>`/`<style>` | 1,967 chars | — |
| **JSON-LD `description` alone** | 7,136 chars | **~1,800** |

Three problems fall out of those numbers. (1) The page is unusable today — 576KB of Angular markup into haiku is prohibitive and likely exceeds context. (2) `looks_js_shell` would classify it a SHELL (visible-text ratio 0.0034 < the 0.01 threshold) and launch Playwright — even though the full listing **is** in the HTML, inside a `<script type="application/ld+json">` block the heuristic strips before measuring. (3) The JSON-LD carries `hiringOrganization: "GitHub, Inc."` — the real employer, which is exactly the field a platform-branded board (UCTalent) got wrong.

`JobPosting` JSON-LD is a web standard that Google for Jobs effectively requires, so most ATS platforms emit it. Parsing it is free, deterministic, and general.

## Goal

1. Before any browser fallback, parse `JobPosting` JSON-LD out of fetched HTML and **prefill** `Job` fields from it.
2. Shrink the extract payload from whole-page HTML to the listing description (~99% smaller on SPA boards).
3. Only fall through to the JS-shell heuristic / Playwright when no usable `JobPosting` is found.

## Components

### 1. Parser (`job_pipeline/sources/jsonld.py`)

`extract_jobposting(html: str) -> dict | None` — returns a normalized dict or `None`.

- Collect every `<script type="application/ld+json">` block; tolerate malformed JSON (skip that block, never raise).
- Each block may be a single object, a list, or a `{"@graph": [...]}` wrapper — walk all three. Take the first node whose `@type` is `JobPosting` (or a list containing it).
- Field mapping (all optional; omit rather than emit junk):
  - `title` → `title`
  - `hiringOrganization.name` → `company`
  - `description` → `description_html`, HTML-stripped to plain text
  - `jobLocation.address` → `location`, joined `addressLocality, addressRegion` (or `addressCountry` when region absent)
  - `baseSalary.value` → `comp_min`/`comp_max`/`comp_currency`/`comp_period` (`unitText` `YEAR`→annual, `HOUR`→hourly)
  - `datePosted`, `employmentType` → returned for future use; not written to `Job` in this spec.
- **Placeholder rejection (binding).** Real boards emit filler. Treat as absent: any string value equal (case-insensitively) to `UNAVAILABLE`, `N/A`, `NOT SPECIFIED`, or empty/whitespace; and any salary whose `value`/`minValue`/`maxValue` are all `0` or missing. The GitHub fixture has `addressLocality: "UNAVAILABLE"` and a zeroed `baseSalary` — both must come back absent, not as literal `"UNAVAILABLE"` in the note.

### 2. Wiring (`job_pipeline/sources/fetch.py`, manual + scrape sources)

`fetch_listing_html` (from the js-fallback spec) gains a companion used by the sources:

`fetch_listing(url, js_fallback=True) -> tuple[str, dict]` → `(raw_text, prefill)`

1. Plain GET.
2. `extract_jobposting(html)`; if it yields at least `title` **and** (`description` or `company`), return `(description_text, prefill)` — **`raw_text` becomes the listing description, not the page HTML.** That is the token win, and it is safe because after `fix/hard-filter-extracted-fields` the only consumer of `raw_text` is the extract prompt (dedup keys on URL; hard_filter reads extracted fields).
3. Otherwise fall through to the existing policy: `looks_js_shell` → `browser_get_text` → re-run `extract_jobposting` on the rendered HTML (SPAs often inject JSON-LD client-side) → else return the raw HTML unchanged.

Sources apply `prefill` by `setattr` onto the `Job` before stages run. **Gap-filling extract (E2 Task 4) then only writes the still-blank fields**, so the agent contributes the summary and anything JSON-LD lacked — it cannot contradict `company`, which is the UCTalent failure mode.

Trace one line per job: `jsonld: prefilled title, company, description (3 fields)` or `jsonld: none found`.

### 3. Config

`fetch: {jsonld: true}` alongside the existing `js_fallback` flag (`FetchConfig`, default `True`). `false` skips parsing entirely — an escape hatch if a board emits wrong structured data.

## Testing (no network, no browser)

- Parser: GitHub-shaped fixture (single `JobPosting`, `UNAVAILABLE` address, zeroed salary) → title/company/description present, location and comp **absent**; `@graph` form; array form; multiple blocks where only one is a `JobPosting`; malformed JSON block skipped without raising; page with no JSON-LD → `None`.
- Salary mapping: `unitText: YEAR` → annual, `HOUR` → hourly; min/max both populated; single-value form.
- HTML stripping: description with `<p>`/`<ul>` markup → plain text, entities decoded.
- `fetch_listing`: JSON-LD hit returns description as `raw_text` and never calls the browser fn (monkeypatched); no JSON-LD falls through to shell heuristic; browser-rendered HTML re-parsed for JSON-LD.
- Integration (MockRunner): a job prefilled from JSON-LD reaches publish with `company` from `hiringOrganization` even when the mock extract reply contradicts it (guards the gap-fill contract).

## Non-Goals

- No schema.org types beyond `JobPosting` (no `Organization` crawling for employer enrichment — that is the VEC batch).
- No microdata/RDFa — JSON-LD only; the others are rare on job boards and much fiddlier.
- Does not replace ATS API mappers: when a company resolves to greenhouse/lever/ashby, the API is still preferred (richer, paginated, no HTML at all).
- No caching of parsed results (per-run cost is already negligible).
