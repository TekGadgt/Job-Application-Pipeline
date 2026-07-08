# Vault Import — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Depends on:** Application Status spec (2026-07-03) — imported notes carry `application_status`, which must exist in the note schema first.
**Motivation:** Ryan's pre-pipeline manual tracker lives in another Obsidian folder with evolved-over-time frontmatter (`position`, `status: In Talks`, `date-applied`, sometimes-empty `website`, no company field, VEC blocks in some bodies). He wants ONE process: old applications converted into pipeline-schema notes in the output vault, without any AI analysis. Others adopting the tool will have their own shapes — so the mapping is config, not code.

## Goal

`job-pipeline import` converts an existing folder of markdown notes into pipeline-format notes in `output.vault` — frontmatter remapped per user-defined config, bodies preserved, seen-index marked — spending zero tokens and never running stages. One-time by intent, idempotent by design (safe to re-run as you clean up old notes).

## Distinct from the seeder (binding)

`existing_vault` seeder = "the pipeline should *ignore* these jobs" (dedup-only, notes stay where they are, unchanged). `import` = "the pipeline should *adopt* these applications" (converted notes live in the output vault; dedup marking comes along for free). Both remain; README gets a two-line "which do I want?" note. The seeder is unchanged by this spec.

## Config Syntax (binding)

A top-level `import:` block in `pipeline.yaml` (reviewable, repeatable — not one-shot CLI flags):

```yaml
import:
  path: ~/Documents/old-job-tracker      # folder of old notes (recursive)
  fields:                                # pipeline-canonical <- old frontmatter key
    position: position
    application_status: status
    date_of_contact: date-applied
    source_url: website
  company_from: filename                 # filename | <frontmatter key>. Default: "company"
  keep_unmapped: true                    # default true: carry unrecognized old keys through
```

- `fields` maps **canonical pipeline frontmatter keys** (left) to **old-note keys** (right). Only mappable canonicals are accepted (unknown left-hand keys fail at load, naming the key): `company`, `position`, `type_of_work`, `source_url`, `date_found`, `date_of_contact`, `employer_address`, `employer_phone`, `employer_email`, `employer_contact_person`, `result_of_contact`, `application_status`, `score`.
- Missing old keys per note are fine (templates evolve): the canonical gets its normal default.
- `company_from: filename` uses the old note's stem as the company (Ryan's vault pattern); any other value is treated as a frontmatter key.
- `keep_unmapped: true` appends old keys that weren't consumed by any mapping (and aren't pipeline-canonical) to the new frontmatter verbatim (`has-referral`, `salary-expectation`, wiki-linked `resume`, …) — data is never silently dropped. `false` drops them.

## Import Behavior

Per old note (recursive `**/*.md` under `path`):

1. Parse frontmatter with the same tolerant approach as the seeder (skip non-frontmatter files; count and report skips).
2. Build the pipeline frontmatter: canonical defaults → overlaid with mapped values → `status: imported` (NOT `to_review` — historical notes must never look untriaged, and skip-on-edit's `status != "to_review"` check permanently protects them from any future republish) → `application_status` defaulting to `Unsubmitted` only when unmapped/absent.
3. **Identity:** `job_id` = sha256 of `source_url` when present (identical derivation to `Job`), else sha256 of the old note's vault-relative path (stable across re-runs). Note filename uses the existing `path_for` slug scheme.
4. **Body preserved verbatim** below the new frontmatter (VEC blocks and all). No AI summarization, no restructuring — zero tokens is a hard property of this command.
5. **Seen-index marked:** URL row when `source_url` present; fuzzy key when company+title resolve (same `make_fuzzy_key`, same "|"-guard as the seeder). This is why a fully imported vault no longer needs the `existing_vault` seeder pointed at the old folder.
6. **Idempotent/non-destructive:** if the target note path already exists, skip it (report count). Never overwrites, no `--force` (deliberate: import is additive; fixing an import means deleting the generated note and re-running).
7. Summary line: `imported=N skipped_existing=N skipped_unparseable=N seen_marked=N`.

## CLI

`job-pipeline import [--config ...] [--dry-run]` — `--dry-run` prints the per-note plan (old path → new path, mapped fields) without writing anything. Errors clearly if the `import:` block is absent.

## Testing (no network, no tokens)

- Config: `import:` block parses; unknown canonical in `fields` fails at load naming the key; block absent → `import` command exits non-zero with a clear message.
- Mapping: old-shaped fixture (Ryan's template, anonymized) → new note with mapped `application_status`/`date_of_contact`/`position`; missing old keys → defaults; `company_from: filename`; `keep_unmapped` both ways.
- Identity/idempotence: URL note keyed by URL-hash; URL-less note keyed by relative-path-hash; second run imports nothing new; existing target skipped.
- Seen-index: URL row and fuzzy row marked appropriately; URL-less+company-less note marks nothing but still imports.
- Body preservation byte-exact; `status: imported` protects via existing `is_user_touched`.
- `--dry-run` writes nothing (assert vault dir unchanged).

## Acceptance

- `pipeline.example.yaml`: commented `import:` block.
- README: "Importing an existing tracker" subsection + the seeder-vs-import two-liner.

## Non-Goals

- No AI enrichment of imported notes (no extract/skill-gap/score — ever, for this command).
- No value transformation beyond copy (no date reformatting, no status-vocabulary translation — normalize values in your old vault or post-import).
- No sync-back to the old folder, no deletion of old notes, no watch mode.
- No per-note mapping overrides.
