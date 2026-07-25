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

## Batch E — Intake expansion *(blocked by B — in progress, executed in waves)*
APIs everywhere possible; scrape only as fallback. Pull the minimal fetcher seam from shelved Batch C as needed.
Too big for one plan — each wave is its own plan/branch/PR (or an operational run with no PR):
- **E1 — Research seed** *(operational, DONE 2026-07-25)*: ran `docs/CompanyResearchPrompt.md` via multi-agent workflow (10 researchers → dedup → 17 verifiers → synthesis). Result: **124 companies** in `config/companies.json`, 115 with live careers URLs, **25 enabled for wave 1**. ATS histogram: ashby 37, greenhouse 37, unknown 39, lever 7, workable 4 (never fetched), workday 1, bamboohr 1. Of wave 1, **13 are fetchable today** (greenhouse/lever mappers exist) and **12 await the E3 ashby mapper**. Lesson for re-runs: run `detect()` over the checkpoint locally first — it resolves ATS/slug for free; only marketing-page entries need agents.
  - **E1 follow-up batches** *(thin domains from batch 1, each its own research session)*: climate/energy via Climatebase + YC climate tag (only 5 found); accessibility via WebAIM vendor directory + a11yproject (7); logistics/supply chain via HN who's-hiring keyword filter + FreightWaves (8); legaltech via Clio marketplace + LawSites roundups (10); edtech via EdSurge database + YC education tag (11); media/publishing via Digiday/Press Gazette, plus Wellfound/Otta as the LinkedIn substitute (11). Batch 1 also skewed late-stage (43 Series C+ vs 12 Series A) — an early-stage sweep of recent YC batches + Wellfound seed listings is worth its own session. Hampton Roads/Virginia regional employers were never targeted.
  - **E1b — LinkedIn follow-up batch** *(export received 2026-07-25; filtering DONE, board-resolution NOT started)*: `config/Connections.csv` (gitignored) → 354 connections / 252 companies. Filter applied = `CompanyResearchPrompt.md`'s avoid-list (agencies/consultancies 8, defense/military 6, crypto 0, surveillance 0) + Ryan's former employers (Trader Interactive, TechArk, MAXX Potential) + non-companies ("Freelance" etc.) + already-in-registry → **225 candidates**, saved to `config/e1b-network-candidates.json` (gitignored). Universities are NOT excluded (ODU is a valid target depending on roles).
    - **Key finding:** of the **14 companies with ≥2 connections** (`config/e1b-network-multi.json`), **7 are Hampton Roads/Virginia employers** — InMotion Hosting (VB, 8 connections), PRA Group (Norfolk), Dollar Tree (Chesapeake), Sentara Health (Norfolk), ODU (Norfolk), Hamilton Beach + CoStar (Richmond). Batch 1's channels (YC/HN/remote lists) structurally cannot surface established regional employers, so the network fills exactly the regional gap noted below. Network/registry overlap is only 5/124 — E1b is additive, not redundant.
    - **Next steps:** (1) resolve boards for the 14 multi-connection companies (~3 haiku agents; a run was started and cancelled for session limits); (2) the 210 single-connection candidates are weak signal (one-person LLCs, a conference, small studios) — triage by NAME ONLY with 1-2 cheap agents before spending any fetch budget on them. Registry entries get `source: "linkedin_export"` and populate the `contacts` field.
- **E2 — Registry infrastructure** *(plan/PR)*: the `2026-07-24-company-registry-discovery` spec's code — registry loader + example file, `type: companies` meta-source, gap-fill extract, URL harvesting, score context, wave gating.
- **E3 — Mappers by demand** *(plan/PR; histogram now in — ASHBY IS THE PRIORITY)*: `2026-07-16-ashby-source` first — ashby ties greenhouse as the most common platform (37 each) and blocks 12 of the 25 wave-1 companies. SmartRecruiters/Workday scored 0 and 1 respectively in this batch, so both are deferred until a later research batch justifies them. Non-standard vendors seen (Rippling ×3, Personio, Dover, join.com, Jobylon, JazzHR, Welcome to the Jungle, Notion) are E4 scrape candidates, not mappers.
- **E4 — Scrape fallback** *(plan/PR)*: `2026-07-02-scrape-source` + `2026-07-03-js-fallback-fetcher` for the unknown-platform tail.
- **E5 — Activation** *(operational)*: enable registry waves, watch the FIFO drain — hands off to Batch F.
- `2026-07-16-ashby-source` — `type: ashby` posting-API source (UltiPro stays scrape-only)
- `2026-07-02-scrape-source` — `type: scrape` careers pages (robots.txt, seen-skip, bs4)
- `2026-07-03-js-fallback-fetcher` — `looks_js_shell` + Playwright `[browser]` extra
- `2026-07-24-company-registry-discovery` — `companies.json` machine-owned registry + `type: companies` meta-source, gap-filling extract (prefilled fields become authoritative), URL harvesting via `docs/JobBoardDetection.md` patterns, score-agent company context, wave-gated activation. Seeding = running `docs/CompanyResearchPrompt.md` via multi-agent research (operational step, before mapper build-out; ats_platform histogram picks tier-2 mappers — SmartRecruiters first, Workable never). LinkedIn-export intake deferred.

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
