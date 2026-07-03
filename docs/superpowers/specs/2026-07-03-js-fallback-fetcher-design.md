# JS-Fallback Fetcher — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Depends on:** Observability spec (2026-07-03) is complementary but not required — the empty-extract errored guard is the safety net when this fetcher isn't installed or still comes up dry.

## Goal

Detect that a fetched page is a JS-rendered shell (listing content not in the HTML) and transparently re-fetch it with a headless browser, so SPA job boards (Ashby's `www.ashbyhq.com/careers?ashby_jid=…` route, and similar) work through the manual source — and later the scrape source — without per-site code. Playwright is an **optional extra**: the base install stays browser-free.

## Components

### 1. Fetch seam (sources/base.py → sources/fetch.py)

`http_get_text` grows into a small fetch module (`job_pipeline/sources/fetch.py`) exporting:

- `http_get_text(url, headers=None) -> str` — existing httpx fetch (moved; `sources/base.py` re-exports for compatibility).
- `looks_js_shell(html) -> bool` — free heuristic, no tokens, no browser:
  - strip `<script>`/`<style>`/tags → visible text; if `len(text) < 200` chars, or
  - visible-text-to-HTML byte ratio `< 0.01`,
  → shell. Thresholds are module constants (`MIN_VISIBLE_TEXT = 200`, `MIN_TEXT_RATIO = 0.01`) so forks can tune them.
- `browser_get_text(url) -> str` — Playwright (chromium, headless): navigate, wait for `networkidle` (10s cap), return `page.content()`. Imports playwright lazily inside the function; raises `FetcherUnavailable` (new exception) if the package or browser binary is missing.
- `fetch_listing_html(url, js_fallback=True) -> str` — the composed policy: plain GET; if `js_fallback` and `looks_js_shell(result)`, try `browser_get_text`; on `FetcherUnavailable` log a warning naming the install command and return the shell HTML (downstream guard turns it into a retryable error).

### 2. Wiring

- **Manual source** switches from `http_get_text` to `fetch_listing_html` for detail fetches. The `self._get` monkeypatch seam stays (tests patch the composed function the same way).
- **Scrape source** (spec 2026-07-02, not yet built): its detail-page fetch uses `fetch_listing_html` too — one-line note added to that spec's Fetch Flow when implemented; index pages stay plain GET (link hrefs are present even in shells rarely; if an index is a shell, the scrape source's zero-links result is already visible in run history).
- **Config:** `fetch: {js_fallback: true}` top-level optional block in `pipeline.yaml` (pydantic model `FetchConfig`, default `js_fallback: True`). `false` disables browser fallback entirely (never import playwright).

### 3. Packaging

`pyproject.toml` gains `[project.optional-dependencies] browser = ["playwright>=1.40"]`. README section "JS-rendered pages":

```
pip install -e '.[browser]'
playwright install chromium
```

plus one paragraph on the heuristic and the `fetch.js_fallback` switch. Without the extra, JS-shell pages surface as errored jobs with the guard's "JS-rendered page?" reason — a self-explaining breadcrumb pointing at this section.

## Behavior Matrix

| Page | `[browser]` installed | Result |
|---|---|---|
| Server-rendered | any | plain GET, no browser launched |
| JS shell | yes | browser re-fetch → real content → extract proceeds |
| JS shell | no | warning logged with install hint; extract guard marks errored (retryable) |
| JS shell that stays empty even in browser | yes | extract guard marks errored — no infinite retry loop within a run |

## Testing (no network, no browser in the default suite)

- `looks_js_shell`: true for a fixture SPA shell (`<div id="root">` + big script bundle), false for a real listing fixture and for a short-but-textful page above threshold.
- `fetch_listing_html`: monkeypatched `http_get_text`/`browser_get_text` — shell triggers browser call; non-shell doesn't; `FetcherUnavailable` falls back to shell HTML with a logged warning; `js_fallback=False` never calls the browser fn.
- Manual source: shell fixture flows through to an errored job end-to-end with MockRunner (composes with the extract guard).
- One opt-in `@pytest.mark.integration` test that actually launches chromium against a local `file://` fixture (skipped when playwright missing) — verifies the real plumbing without network.

## Non-Goals

- No per-site selectors/wait conditions, no login/auth flows, no proxy/stealth features (this is a polite tool, not a scraping evasion kit), no browser pooling (one launch per fallback fetch is fine at personal volume), no Playwright for the feeds sources (Greenhouse/Lever/RSS are APIs).
