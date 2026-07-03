# Generic Scrape Source (Company Careers Pages) — Design Spec

**Date:** 2026-07-02
**Status:** Approved for planning
**Scope:** A polite, configurable HTML scraper source for direct company jobs pages. LinkedIn and Wellfound are explicitly **out of scope** (auth walls, active anti-scraping, ToS conflicts — bad fit for a published tool; the manual inbox covers "I saw it there").

## Goal

A `type: scrape` source that takes a careers *index* page, discovers job-detail links on it, fetches each detail page, and emits one `Job` per posting with the page text as `raw_text` — letting the existing extract agent do the structure work. Zero per-site code; per-site behavior lives in `pipeline.yaml`.

## Config Syntax (binding)

```yaml
sources:
  - type: scrape
    url: "https://example.com/careers"        # index page (required)
    link_selector: "a.job-listing"            # CSS selector for job links (default: "a")
    link_pattern: "/jobs/\\d+"                # optional regex; link href must match
    same_host_only: true                      # default true; drop links to other hosts
    max_jobs: 30                              # default 30; cap detail fetches per run
    delay_seconds: 1.0                        # default 1.0; sleep between detail fetches
```

At least one of `link_selector` (non-default) or `link_pattern` should narrow the link set; with both defaults the source still works but will fetch nav links — `max_jobs` and downstream filters bound the damage. Relative hrefs resolve against the index URL (`urljoin`).

## Fetch Flow

1. GET the index page (existing `http_get_text`, but see User-Agent below).
2. Parse links: `soup.select(link_selector)`, keep hrefs matching `link_pattern` (if set), resolve relative URLs, apply `same_host_only`, dedupe while preserving page order.
3. **Skip already-seen URLs before fetching** (see Seen-skip below) — a careers page mostly shows the same postings every run; re-fetching them wastes requests.
4. For each surviving link, up to `max_jobs`: sleep `delay_seconds`, GET the detail page, extract text, emit `Job(source="scrape", url=<detail url>, raw_text=<text>, fetched_at=now)`.
5. Per-page error isolation: one failed detail fetch logs a warning and continues; it does not kill the source (mirrors `run_pipeline`'s per-source isolation one level down). A failed *index* fetch raises — the existing per-source guard in `run_pipeline` handles it.

`on_terminal(job)` is a no-op (like feeds).

## Text Extraction

New dependency: **beautifulsoup4** (ubiquitous, forgiving parser — right choice for a repo people will fork). Helper in `sources/scrape.py`:

- Drop `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>` subtrees.
- `soup.get_text(separator="\n")`, collapse runs of blank lines/whitespace.
- Truncate `raw_text` to 20,000 characters (bounds extract-agent input; typical postings are far under).

No readability heuristics, no main-content detection — the extract agent tolerates boilerplate, and the hard_filter runs on full text anyway (more text = more blocklist surface, which is fine).

## Politeness (binding — this ships in a public repo)

- **User-Agent:** all scrape-source requests send `User-Agent: job-pipeline/<version> (+https://github.com/TekGadgt/Job-Application-Pipeline)`. Add an optional `headers` kwarg to `http_get_text` (default `None`, existing callers unaffected).
- **robots.txt:** before fetching, check the host's robots.txt via `urllib.robotparser` (fetched once per host per run, cached on the source; unreachable/missing robots.txt = allowed). Disallowed URLs are skipped with a logged warning. Not configurable — a published scraping tool respects robots, full stop.
- **Rate:** `delay_seconds` between detail fetches (default 1.0). `time.sleep` — attribute on the source instance (`self._sleep = time.sleep`) so tests can neutralize it, matching the `self._get` monkeypatch pattern in `feeds.py`.

## Seen-Skip Wiring

The scrape source is the first source that benefits from knowing the seen index (skip detail fetches for URLs already processed). Design:

- `ScrapeSource.__init__(..., skip_url: Callable[[str], bool] | None = None)` — a predicate, not the SeenIndex itself (keeps sources decoupled from the store).
- `build_sources` gains an optional `seen: SeenIndex | None = None` parameter; for `type: scrape` entries it injects `skip_url=lambda url: seen.has_url(job_id_for(url))` where `job_id_for` is the same sha256[:16] used by `Job` (extract that into a small function on `core/job.py` — currently inline in `Job.__post_init__`; `Job` calls the shared function so the hash can never drift).
- `run_pipeline` already constructs `seen` before `build_sources` (`core/pipeline.py:75,85`) — pass it through.
- With `skip_url=None` (direct construction, tests) nothing is skipped; the downstream dedup stage still guarantees correctness. Skip is an optimization, dedup is the invariant.

## Out of Scope (documented in README)

- JS-rendered pages (a headless-browser fetcher is a future source; note it, don't build it).
- Pagination on index pages (point the yaml at each page as a separate source entry if needed).
- Auth-walled boards, LinkedIn, Wellfound.
- Structured extraction in the source — that's the extract stage's job.

## Testing (no network, as always)

Fixture HTML files under `tests/fixtures/` (index page with mixed links + two detail pages). Monkeypatch `self._get` (and `self._sleep`) like the feeds tests. Cover:

- Link discovery: selector match, pattern filter, relative-URL resolution, same-host drop, order-preserving dedupe.
- `max_jobs` cap; `skip_url` prevents detail fetches (assert `_get` call list).
- Text extraction: script/style/nav stripped, whitespace collapsed, truncation at 20,000 chars.
- robots.txt: disallowed path skipped; missing robots allowed (monkeypatch the robots fetch).
- Per-page isolation: one detail `_get` raising leaves the other jobs emitted.
- Registry: `type: scrape` constructible from a yaml-shaped dict via `build_sources`, `skip_url` injected.

## Acceptance

- `pipeline.example.yaml` gains a commented-out scrape entry showing the full syntax.
- README source table row + politeness note (UA string, robots, delay) + out-of-scope list.
- `pyproject.toml` adds `beautifulsoup4`.
