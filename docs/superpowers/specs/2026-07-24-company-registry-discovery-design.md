# Company Registry & Discovery — Design Spec

**Date:** 2026-07-24
**Status:** Approved for planning
**Companion specs (Batch E):** `2026-07-16-ashby-source-design.md`, `2026-07-02-scrape-source-design.md`, `2026-07-03-js-fallback-fetcher-design.md`
**Reference docs:** `docs/JobBoardDetection.md` (tracked — ATS detection patterns, API endpoints, tier/ban notes), `docs/CompanyResearchPrompt.md` (gitignored, personal — the research prompt whose JSON output seeds the registry)

**Motivation:** Intake today is a handful of hand-written sources. The first wave of Batch E seeds hundreds of target companies from a research prompt, and every later company arrives ad hoc (a URL in the inbox, a `--url` run). Hand-maintaining hundreds of `{type: greenhouse, board: x}` lines in `pipeline.yaml` doesn't scale, machine-editing YAML destroys human formatting, and the company metadata the research produces (fit rationale) has no home. Separately, structured ATS sources already prefill `title`/`location` deterministically — and the extract stage clobbers them with an agent re-parse (`extract.py` `setattr`s every reply field unconditionally).

## Goal

1. A machine-owned **company registry** (`companies.json`) is the single home for target companies: seeded by research, appended by URL harvesting, expanded into sources at run time. `pipeline.yaml` stays human-owned.
2. **Extract becomes gap-filling**: deterministic data from structured sources is authoritative; the agent only fills what's still blank.
3. **URL harvesting**: any manually supplied URL matching a known ATS pattern adds its company to the registry automatically.
4. Registry metadata (fit rationale) reaches the **score agent** as company context.
5. Activation is **wave-gated** so the first sweep doesn't flood the agent cap.

## Ownership principle (binding)

Split by who writes it: `pipeline.yaml` = human-owned config (comments, hand-edited, never machine-written). `companies.json` = machine-owned data (comment-free JSON, written by code and by research output; humans *may* edit, machines *never* edit the yaml). `companies.json` is personal targeting data: gitignored, with a tracked `companies.example.json` showing the schema.

## Components

### 1. Registry file (`companies.json`)

A JSON array; each entry carries the research prompt's output schema plus pipeline-owned fields:

```json
{
  "name": "Company Name",
  "website": "https://example.com",
  "careers_url": "https://example.com/careers",
  "ats_platform": "greenhouse",          // detection-doc platform id, or null = unknown
  "slug": "companyname",                  // board token/org slug parsed from careers_url; null until resolved
  "domain": "talent acquisition",
  "company_size": "scaleup",
  "stage": "series_b",
  "location": "San Francisco, CA",
  "remote_policy": "fully_remote",
  "notes": "Why this company is a good target — feeds the score agent.",
  "source": "claude_research_batch_1",   // provenance: research batch id or "url_harvest"
  "enabled": true                         // activation gate (wave-based burn-in)
}
```

Only `name` is required; everything else defaults to null/`enabled: true`. Loader is tolerant (bad entries warn + skip, never crash the run). Schema validation lives in `config.py` alongside the other models; `pipeline.yaml` gains one source line: `- {type: companies, file: companies.json}`.

### 2. Companies source (`sources/companies.py`)

A meta-source registered as `type: companies`. At `fetch()` it reads the registry and expands each `enabled` entry:

- `ats_platform` with a **supported mapper** + non-null `slug` → delegate to that ATS source (greenhouse/lever/ashby/…) and aggregate the jobs. Every job gets `job.company` set from the registry `name` (the board slug is not a display name) and carries the registry entry for downstream context.
- `ats_platform` null/unsupported → delegate to the scrape source (companion spec) using `careers_url`, once scrape lands; until then warn-and-skip with a per-run summary count (no silent truncation).
- `slug` null but `careers_url` matches a detection pattern → resolve and persist the slug back to the registry (one of the two legal machine writes; the other is harvesting).

Per-source failures stay isolated (same one-dead-feed-doesn't-kill-the-run policy as `run_pipeline`).

### 3. Gap-filling extract (`stages/agents/extract.py`)

The one behavioral change to an existing stage: after the runner reply, **only blank fields are written** — `setattr` skips any field the job already carries (non-empty string / non-None). Deterministic prefill from sources becomes authoritative; the agent fills summary, requirements, and comp-parsed-from-prose (which Greenhouse/Lever rarely expose structurally). The extract prompt gains a line listing the already-known fields so the model doesn't waste effort re-deriving them. Extract still runs for every job (the `description` summary is always agent-produced); a job whose extract-owned fields are somehow all filled skips the call entirely.

### 4. URL harvesting (`sources/manual.py` + detection table)

The detection patterns from `docs/JobBoardDetection.md` become a small table in code (`pattern regex → ats_platform, slug group`). When a manual URL (inbox or `--url`) matches, harvesting appends a registry entry — `name` derived from the slug, `source: "url_harvest"`, `enabled: true`, everything else null — and logs `added <slug> as <ats> source`. Duplicate slugs (already in registry) are ignored. The harvested board is fetched on the *next* run, not the current one. Harvesting never blocks the manual job itself.

### 5. Score context (`stages/agents/score.py`)

When the job's company matches a registry entry with non-empty `notes`, the score prompt gains one line: `COMPANY CONTEXT: <notes>`. Cache-stable placement (module-constant prompt with a fill slot, same pattern as `extract_hint`).

### 6. Activation waves & limits

- `enabled: false` entries are skipped by the companies source. The research seed lands with waves pre-assigned (e.g. first ~25 companies `enabled: true`, rest `false`); enabling the next wave is a hand edit or a one-line `jq` — no new tooling (YAGNI until the manual step hurts).
- `max_agent_jobs_per_run: 40` stays the throttle; deferred-FIFO already handles overflow. Drain math documented in README: one wave of N companies × ~M open roles each, at 40/run.
- **Risky platforms policy** (from the detection doc): Workable is never fetched (aggressive IP bans) — the companies source refuses `ats_platform: workable` with a warning. New tier-2 mappers (SmartRecruiters first — documented public API; Workday if the registry histogram justifies POST+pagination work) are built by demand evidenced in the seeded registry, not speculatively; unknown platforms ride the scrape fallback.

### 7. Research execution (operational, not code)

Seeding the registry = running `docs/CompanyResearchPrompt.md` to the letter via a multi-agent workflow: parallel researchers per discovery channel/domain → dedup by company → a verification wave that fetches each `careers_url`, confirms it resolves, and detects `ats_platform`/`slug` via the detection table ("verified, not guessed" is the prompt's own bar) → merged JSON into `companies.json`. Runs *before* mapper build-out so the `ats_platform` histogram picks which tier-2 mappers are worth building. This step is performed in-session with Ryan, not part of the implementation plan.

## Testing (no network, no tokens)

- Registry: loads example file; bad entry warns + skips; `enabled: false` excluded; schema round-trips slug persistence.
- Companies source: expands greenhouse/lever/ashby entries to the right sources with `company` overridden from registry name (mock the per-ATS fetchers); unknown platform counted + skipped; workable refused with warning.
- Gap-fill extract: prefilled `title`/`location` survive an extract reply that contradicts them; blank fields are filled; fully-prefilled extract-owned fields skip the runner call (MockRunner call count).
- Harvesting: greenhouse/lever/ashby URLs append correct registry entries; duplicate slug ignored; non-matching URL appends nothing; registry file round-trips (valid JSON, prior entries untouched).
- Score context: prompt contains registry notes when present, absent otherwise (MockRunner capture).

## Non-Goals

- No LinkedIn-export ingestion in this spec (future discovery source; registry schema already accommodates it via `source`).
- No auto-enable/wave-scheduler tooling, no per-company rate limiting, no registry UI.
- No tier-2 mappers beyond SmartRecruiters committed here — histogram decides (Workday likely; Taleo/Eightfold/iCIMS default to scrape).
- No machine edits to `pipeline.yaml`, ever.
- No change to the no-auto-apply invariant: discovery finds postings; humans apply.
