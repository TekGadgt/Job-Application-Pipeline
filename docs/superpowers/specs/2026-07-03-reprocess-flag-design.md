# Reprocess Flag — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Scope:** Tiny, standalone. Extracted from the Observability & Run History spec (2026-07-03) so it can ship early — re-running a terminally-marked URL is useful *today* (e.g., a posting that was rejected on a bad extraction, or one you want re-scored after editing your profile), independent of the run-history work.

## Goal

`job-pipeline run --url <u> --reprocess` deliberately un-marks the given URL(s) in the seen index before the run, so a previously published or rejected URL flows through the full pipeline again. Without the flag, behavior is unchanged (terminal URLs dedup-reject silently — by design).

## Design

### 1. `SeenIndex.unmark(url_hash) -> bool` (store/seen_index.py)

Deletes the row for `url_hash`; returns whether a row existed. Deleting the row also clears its stored `fuzzy_key` (same row, one DELETE) — so the re-run redoes both URL dedup **and** fuzzy dedup for that entry. Rows written by *other* sources/URLs that share the fuzzy key are untouched (if the same role is still marked seen via a different URL, `dedup_fuzzy` will still catch it — correct behavior, not a bug).

### 2. CLI (cli.py)

- `run` gains `--reprocess` (store_true). Valid **only with `--url`**: `--reprocess` alone exits non-zero with `--reprocess requires --url (no blanket un-marking)`.
- Before the run: for each `--url` value, compute the job id (`hashlib.sha256(url.encode()).hexdigest()[:16]` — same derivation as `Job.__post_init__`) and call `unmark`. Log one INFO line per URL: `reprocessing <url> (was seen)` or `reprocessing <url> (was not seen)` — the second case is not an error, just informative.
- The seen db lives at `cfg.output.vault / ".job_pipeline.seen.sqlite"` — same resolution `run_pipeline` uses. Open it once for unmarking; the run then proceeds exactly as a normal `--url` run (URL-only, sources/inbox skipped — existing semantics).

### 3. Interplay with skip-on-edit (README note)

Re-running a published URL re-publishes the note **only if** its `status` is still `to_review`. If you've advanced the note, publish skips it (protection working as intended); add `--force` to overwrite. One README sentence under the run examples: `job-pipeline run --url <u> --reprocess [--force]  # re-run a previously processed URL; --force also overwrites an edited note`.

## Coordination

The Observability spec (2026-07-03) previously carried this flag as its CLI item 3; it is amended to reference this spec instead. Its `why <url>` command remains the natural companion (see why it was rejected → `--reprocess` it), but neither depends on the other.

## Testing (no network, no tokens)

- `SeenIndex.unmark`: removes an existing row (subsequent `has_url` false, `has_fuzzy` false for that row's key); returns False for unknown hash; other rows untouched.
- CLI: `--reprocess` without `--url` exits non-zero with the message; with `--url`, the seen row is gone before `run_pipeline` is invoked (monkeypatched `run_pipeline` + pre-seeded tmp db, matching `tests/test_cli.py` conventions).
- e2e (MockRunner): publish → mark seen → second run dedup-rejects → third run with `--reprocess` publishes again.

## Non-Goals

- No blanket/pattern un-marking, no `--reprocess` for feed sources, no fuzzy-key-wide clearing, no run-history awareness (that's the observability spec), no note deletion.
