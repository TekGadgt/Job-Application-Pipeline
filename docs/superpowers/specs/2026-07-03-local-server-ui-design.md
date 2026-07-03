# Local Server & Web UI — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning — build LAST; hard dependency on the Observability & Run History spec (2026-07-03), which is the entire data layer this reads.

## Goal

`job-pipeline serve` starts a local, single-user web server that:

1. Surfaces run history — runs, per-job outcomes, reject/error reasons, stage traces — alongside links to the published Obsidian notes.
2. Accepts new URLs into the queue (writes the existing inbox file — no new queue mechanism).
3. Triggers runs on demand and on a schedule, with all runs **serialized through one executor** so a scheduled run and a manual one can never race the state db or inbox.

The CLI remains fully standalone: the server is an optional supervisor over the same `run_pipeline()` function, never a requirement. Nothing binds beyond localhost by default.

## Explicitly ruled out

Electron/Tauri desktop shell — a Python repo shouldn't grow a Node/Rust toolchain for a localhost dashboard. If a dock-icon app is ever wanted, it can wrap this same server. Revisit only after this ships.

## Components

### 1. Run lock (store/run_lock.py) — shared by CLI and server

Cross-process serialization, not just in-process: an advisory `fcntl.flock` on `<vault>/.job_pipeline.lock`, exposed as a context manager `run_lock(db_dir, timeout=0)`. `run_pipeline` acquires it internally (so *every* entry point is covered); a locked-out CLI run exits with "another run is in progress". This lands with the server spec but protects cron-vs-manual overlap on its own.

### 2. Server (server/app.py) — FastAPI, optional extra

`[project.optional-dependencies] server = ["fastapi>=0.110", "uvicorn>=0.29"]`. `job-pipeline serve [--host 127.0.0.1] [--port 8288]` starts uvicorn. JSON API:

- `GET /api/runs?limit=20` — run rows (id, timestamps, counts)
- `GET /api/runs/{id}/jobs` — run_jobs rows for a run
- `GET /api/jobs?url=…` — the `why <url>` query (all history for a URL + seen status)
- `POST /api/inbox` `{url}` — append to the configured inbox file (400 if no inbox configured)
- `POST /api/run` — enqueue a pipeline run; returns `{queued: true, position: n}`
- `GET /api/status` — idle/running, current run id, next scheduled run time, schedule config

Run execution: a single `asyncio.Queue` consumed by one worker task that calls `run_pipeline()` in a thread executor (it's sync) under the run lock. Manual and scheduled triggers both just enqueue; queue depth capped at 1 pending (a second `POST /api/run` while one is queued returns `{queued: false, reason: "already queued"}` — runs are idempotent-ish; stacking them is pointless).

### 3. Scheduler (server/scheduler.py)

No new dependency: an asyncio task that reads `schedule:` from `pipeline.yaml` and enqueues a run every interval.

```yaml
schedule: {every_minutes: 240, quiet_hours: [23, 7]}   # optional block
```

`quiet_hours: [start, end]` (local time, wrap-around supported) suppresses scheduled enqueues — job boards don't change at 3am and neither should your usage window burn. Absent `schedule:` block → scheduler task not started; `serve` is then dashboard-only. Cron remains a fully supported alternative for CLI-only users (README keeps both recipes).

### 4. Frontend (server/static/) — one page, zero build step

Single `index.html` + one JS file (vanilla, `fetch()` against the API) served by FastAPI's static files. No node, no bundler, no framework — the repo must stay `pip install`-only. Views:

- **Runs list** (default): table of recent runs; expanding a run lists its jobs with outcome badge, stage, reason.
- **Job drill-down:** decoded trace timeline; for published jobs an `obsidian://open?path=…` link to the note (README notes this needs Obsidian's URI handler; a plain vault-relative path is shown alongside).
- **Queue form:** URL input → `POST /api/inbox`, with the current inbox contents listed (read-only).
- **Header:** status pill (idle/running/next run at HH:MM) + "Run now" button.

Polling (2s while a run is active, 30s idle) — SSE/websockets are YAGNI at one user.

### 5. Security posture (README, one paragraph)

Localhost bind by default; no auth (single-user, local). Binding to another interface is possible via `--host` but explicitly documented as "you're exposing your job search and run-trigger to that network — put it behind Tailscale or don't do it."

## Testing

- Run lock: second acquirer with `timeout=0` raises/exits; released on exception; covers CLI-vs-CLI via two processes in one test (subprocess spawn is acceptable here, still no network).
- API: FastAPI `TestClient` against a seeded tmp state db — each endpoint's shape; `POST /api/inbox` appends exactly one line; `POST /api/run` with a stubbed executor records an enqueue; double-enqueue returns `already queued`.
- Scheduler: interval/quiet-hours logic as a pure function (`should_fire(now, cfg)`) unit-tested across wrap-around midnight cases; the asyncio loop itself gets one fake-clock test.
- Frontend: not unit-tested (vanilla JS, no toolchain); API contract tests are the safety net. One manual QA checklist in the plan instead.

## Non-Goals

- No auth/multi-user, no HTTPS, no editing notes from the UI (Obsidian owns notes), no config editing from the UI, no run cancellation mid-flight (v1: wait it out), no CLI-delegates-to-server transport (the run lock already prevents races; delegation is a future nicety), no persistence of schedule state across restarts (next fire time recomputed from config).
