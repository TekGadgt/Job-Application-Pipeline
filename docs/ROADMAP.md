# Roadmap — Spec Batches

All open specs (in `docs/superpowers/specs/`) bundled into implementation batches.
Each batch = one branch → one plan (`docs/superpowers/plans/`) → subagent-driven build → one PR.
Ordering rule: a batch starts only when the batches it's **blocked by** have merged.

Execution order: **B → B2 → C → D → E → F → G → H** (value-first, then structure, then the fan-out).

## Batch B — Vault output *(unblocked — next up)*
Everything that lands in notes; one golden-test rebase for all three.
- `2026-07-03-comp-in-notes` — comp frontmatter keys + `## Compensation` section
- `2026-07-03-application-status` — user-owned field; extends `is_user_touched`
- `2026-07-03-vault-import` — `job-pipeline import`, `fields:` map, `keep_unmapped` (needs application-status; satisfied in-batch)

## Batch B2 — Normalization gates *(unblocked; small)*
Deterministic-only, no batch dependencies; the modular pre-gate normalizer family (each normalizer sits immediately before the filter it feeds).
- `2026-07-16-location-normalization` — `normalize_location` stage before `dedup_fuzzy`/`location`, shared canonicalizer normalizes profile metros at load, metro list collapsed; `locations.relocation` flag accepts all locations. (Motivated by the Colonial Williamsburg `Virginia`-vs-`VA` reject.)
- `2026-07-18-comp-normalization` — `normalize_comp` stage before `salary`: annualize + convert `comp_max` to the floor currency (`salary_currency`, `fx_rates` override, static built-in table); salary stage becomes a pure compare. (Fixes live bug: `comp_currency` is ignored, so a £90k listing rejects against a $100k floor.)

## Batch C — Modularity structure *(unblocked; gates D/E/F)*
All house conventions land together. Biggest batch (~8 tasks), mostly mechanical; split at the store-backends boundary if unwieldy.
- `2026-07-03-source-module-split` — `feeds.py` → `rss/greenhouse/lever.py` + RSS hardening + seeders `__init__` aggregator
- `2026-07-03-stage-context` — `StageContext.from_context`; deletes the `build_stages` deps dict
- `2026-07-03-store-backends` — `StateStore`/`Publisher` protocols + registries; `sqlite`/`obsidian` backends

## Batch D — Multi-provider runners *(blocked by C)*
- `2026-07-02-multi-provider-runners` — `models: {stage: [provider:model, …]}` chains, `ModelChain`, runner registry, `runners/` package

## Batch E — Intake expansion *(blocked by C)*
Built together: scrape's detail fetches use the fetcher seam.
- `2026-07-02-scrape-source` — `type: scrape` careers pages (robots.txt, seen-skip, bs4)
- `2026-07-03-js-fallback-fetcher` — `looks_js_shell` + Playwright `[browser]` extra
- `2026-07-16-ashby-source` — `type: ashby` posting-API source (UltiPro deferred to scrape)

## Batch F — Observability *(blocked by C; gates H)*
- `2026-07-03-observability-run-history` — errored guard, terminal-outcome logging, `runs`/`run_jobs` tables, `log`/`why` commands, retires `keep_rejects`

## Batch G — Resume match *(blocked by D)*
- `2026-07-03-resume-match` (rev 2026-07-09) — labeled resumes + master inventory, publish-gated stage, wikilinked recommendation

## Batch H — Local server & web UI *(blocked by F; last)*
- `2026-07-03-local-server-ui` — flock run lock, FastAPI `[server]` extra, scheduler, vanilla-JS dashboard

## Done
- `2026-07-02-job-application-pipeline-design` — core pipeline (merged)
- `2026-07-02-stage-package-refactor` — PR #1 (merged)
- `2026-07-02-extract-hints` — PR #2 (merged)
- **Batch A — Run hygiene** — PR #3 (merged 2026-07-09): location-aware fuzzy dedup (`2026-07-09-location-aware-fuzzy-dedup`), `score_floor` stage (`2026-07-09-score-floor`), `--reprocess` flag (`2026-07-03-reprocess-flag`); plan `2026-07-09-batch-a-run-hygiene`
