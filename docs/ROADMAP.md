# Roadmap — Spec Batches

Re-cut 2026-07-23 after a usage review: the pipeline was over-filtering (see `2026-07-23-lean-core-design.md`). Philosophy: **filter almost nothing deterministically; let the fit score carry judgment; surface everything in the note.** Each batch = one branch → one plan (`docs/superpowers/plans/`) → subagent-driven build → one PR. A batch starts only when the batches it's **blocked by** have merged.

Execution order: **L → B → E → F → VEC** (lean the core, land vault value, expand intake, then observability to handle the volume, enrichment last).

## Batch L — Lean core *(unblocked — next up)*
- `2026-07-23-lean-core` — delete location/salary gates, `dedup_fuzzy` record-only (URL is the only hard dedup), dead profile config removed (`locations`, `salary_floor`, `salary_not_listed`, `must_have_skills`, `nice_to_have`, `keep_rejects`). `hard_filter` and optional `score_floor` explicitly retained.

## Batch B — Vault output *(blocked by L)*
Everything that lands in notes; one golden-test rebase for all three, plus the new surfacing keys.
- `2026-07-03-comp-in-notes` — comp frontmatter keys + `## Compensation` section; **rebase adds `location` frontmatter key and `possible_duplicate`/fuzzy-key surfacing** (data the lean core keeps but publish currently drops).
- `2026-07-03-application-status` — user-owned field; extends `is_user_touched`
- `2026-07-03-vault-import` — `job-pipeline import`, `fields:` map, `keep_unmapped` (needs application-status; satisfied in-batch)

## Batch E — Intake expansion *(blocked by B)*
APIs everywhere possible; scrape only as fallback. Pull the minimal fetcher seam from shelved Batch C as needed.
- `2026-07-16-ashby-source` — `type: ashby` posting-API source (UltiPro stays scrape-only)
- `2026-07-02-scrape-source` — `type: scrape` careers pages (robots.txt, seen-skip, bs4)
- `2026-07-03-js-fallback-fetcher` — `looks_js_shell` + Playwright `[browser]` extra
- **Company discovery (spec TBD, brainstorm at batch start)** — "what adding new sources looks like." Candidate intakes: (1) initial curated sweep of companies matching Ryan's experience; (2) HN "Who is hiring?" RSS mined for *companies and their ATS board links*, not listings; (3) LinkedIn data export → connections' companies → their job boards; (4) slug-harvesting from board URLs already flowing through the manual inbox. Note: Greenhouse/Lever/Ashby have no first-party "list all boards" endpoint — discovery is ours to build.

## Batch F — Observability *(blocked by E — the source fan-out makes it urgent)*
- `2026-07-03-observability-run-history` — errored guard, terminal-outcome logging, `runs`/`run_jobs` tables, `log`/`why` commands. (Item 5, keep_rejects retirement, is fast-forwarded by Batch L.)

## Batch VEC — Enrichment *(last)*
- **VEC enrichment (spec TBD)** — opt-in agent stage before publish: web-fetch employer address/phone/email when the listing lacks them, so frontmatter works as the VEC work-search record.

## Shelved *(2026-07-23 re-cut — on file, revive if needed)*
- Batch B2 normalization gates: `2026-07-16-location-normalization` (+relocation flag), `2026-07-18-comp-normalization` — gate-serving machinery; gates are gone
- Batch C modularity: `2026-07-03-source-module-split`, `2026-07-03-stage-context`, `2026-07-03-store-backends` (E may cherry-pick the fetcher seam)
- Batch D: `2026-07-02-multi-provider-runners`
- Batch G: `2026-07-03-resume-match` (rev 2026-07-09)
- Batch H: `2026-07-03-local-server-ui`

## Done
- `2026-07-02-job-application-pipeline-design` — core pipeline (merged)
- `2026-07-02-stage-package-refactor` — PR #1 (merged)
- `2026-07-02-extract-hints` — PR #2 (merged)
- **Batch A — Run hygiene** — PR #3 (merged 2026-07-09): location-aware fuzzy dedup, `score_floor` stage, `--reprocess` flag; plan `2026-07-09-batch-a-run-hygiene`
