# Observability & Run History — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Motivation:** A rejected job currently vanishes: the reason lives on the in-memory `Job` and is never logged, printed, or persisted (`keep_rejects: true` is dead config — rejected jobs short-circuit before publish). Real incident: a JS-rendered Ashby page 200'd, extracted empty fields, was rejected as `location not allowed: ''` with no visible explanation, and was permanently marked seen. This spec makes every outcome inspectable and stops garbage extractions from becoming terminal.

## Goal

1. Every terminal outcome (published/rejected/errored) is logged with its reason and persisted to a queryable run history.
2. Extraction that produces no real content marks the job **errored** (retryable), never rejected (terminal).
3. CLI commands answer "what happened?" (`log`) and "why this URL?" (`why`) after the fact, and `--reprocess` un-marks a URL for a re-run.

This is the data layer the future local server/UI spec (2026-07-03) reads; it must be useful standalone from the terminal.

## Components

### 1. Empty-extract errored guard (stages/agents/extract.py)

After the runner reply, if `title` **and** `location` are both empty strings, call `job.mark_errored("extract", "no listing content extracted — JS-rendered page?")` and return (do not set the empty fields' trace as success). Errored is non-terminal: the URL is not marked seen and retries next run. Rationale: a real posting always yields at least a title; company alone (site branding) doesn't count — exactly the Ashby-shell failure mode.

### 2. Terminal-outcome logging (core/pipeline.py + cli.py)

In `run_pipeline`'s terminal loop, log one line per non-published job:

- rejected: `log.info("rejected %s at %s: %s", job.url, <stage>, job.reject_reason)`
- errored: `log.warning("errored %s at %s: %s", job.url, <stage>, <error>)`

(Stage and reason come from the existing `mark_rejected`/`mark_errored` fields/trace.) The CLI summary additionally prints reject/error lines under the counts, so `--url` one-offs explain themselves without log-level spelunking:

```
published=0 rejected=1 errored=0 deferred=0
  ✗ https://…  location: location not allowed: ''
```

### 3. Run-history store (store/run_history.py)

New tables in the **same sqlite file** as the seen index (one state db, one path to back up). Managed by a `RunHistory` class mirroring `SeenIndex`'s lazy-connection pattern:

```sql
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  started_at TEXT NOT NULL,
  finished_at TEXT,
  published INTEGER, rejected INTEGER, errored INTEGER, deferred INTEGER
);
CREATE TABLE IF NOT EXISTS run_jobs (
  run_id INTEGER NOT NULL REFERENCES runs(id),
  url TEXT NOT NULL,
  url_hash TEXT NOT NULL,
  source TEXT NOT NULL,
  company TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  outcome TEXT NOT NULL,          -- published | rejected | errored | deferred
  stage TEXT NOT NULL DEFAULT '', -- terminal stage for rejected/errored
  reason TEXT NOT NULL DEFAULT '',
  score REAL,
  trace TEXT NOT NULL DEFAULT '[]'   -- Job.trace as JSON
);
CREATE INDEX IF NOT EXISTS run_jobs_url_hash ON run_jobs(url_hash);
```

`run_pipeline` opens a run row at start, writes one `run_jobs` row per processed job (deferred jobs included, `outcome='deferred'`), and closes the run row with the summary counts. History is append-only; every run's record is kept (rows are tiny; pruning is YAGNI until proven otherwise).

### 4. CLI commands (cli.py)

- `job-pipeline log [--last N]` (default 5): recent runs — id, started_at, counts — then per-job lines for the most recent run (outcome, stage, reason, url).
- `job-pipeline why <url>`: hash the url, print every `run_jobs` row for it (newest first) with outcome/stage/reason and the decoded trace; also say whether the url is currently in the seen index.
- `job-pipeline run --url <u> --reprocess`: before fetching, delete the seen-index row(s) for the given `--url` values so terminal-marked URLs can be re-run deliberately. `--reprocess` without `--url` is an error (no blanket un-marking).

Both new commands need only `--config` (to locate the db via the vault path).

### 5. `keep_rejects` retired (config.py, example yaml, README)

Run history supersedes the never-implemented reject-notes idea. `output.keep_rejects` is removed from `pipeline.example.yaml` and the README; the config field stays accepted (so existing files don't break) but is ignored, documented as deprecated in the field's description. **Flagged for user review** — the alternative (writing reject stub notes into the vault) was rejected as vault clutter: Obsidian holds actionable jobs, sqlite holds forensics.

## Testing (no network, no tokens)

- Extract guard: empty title+location → errored, trace shows extract error, publishable fields untouched; title present + empty location → proceeds (location stage's job to judge).
- RunHistory: run row opened/closed with correct counts; one row per job incl. deferred; trace round-trips JSON; `why`-style query by url_hash returns newest-first.
- run_pipeline integration (MockRunner): rejected job produces a run_jobs row with stage+reason matching `mark_rejected`; errored job is recorded but not seen-marked (existing invariant, now asserted against history too).
- CLI: `log` and `why` output against a seeded tmp db (golden substrings, not full-text asserts); `--reprocess` deletes the right row and the job re-processes; `--reprocess` without `--url` exits non-zero with a clear message.
- Logging: caplog asserts the rejected/errored lines.

## Non-Goals

- No vault reject notes, no HTML/UI (that's the server spec), no schema migrations framework (`CREATE TABLE IF NOT EXISTS` is the migration story at this stage), no retention/pruning options, no changes to seen-index semantics (errored-is-retryable already holds; the guard just routes the JS-shell case into it).
