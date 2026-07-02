# Job Application Pipeline

A personal, extensible pipeline that discovers job listings, filters and scores them
against a personal profile, and publishes ranked matches as Obsidian notes that double
as Virginia Employment Commission (VEC) work-search records. **No automated applying.**

## Stage Diagram

Cheap deterministic filters run first, dropping jobs before any agent tokens are spent.

```
INTAKE ──▶ DEDUP ──▶ HARD-FILTER ──▶ EXTRACT ──▶ DEDUP-FUZZY ──▶ LOCATION ──▶ SALARY ──▶ SKILL-GAP ──▶ SCORE ──▶ PUBLISH
 (feeds +   (Python,  (Python,        (AGENT,     (Python,        (Python)     (Python)   (AGENT,       (AGENT,   (Python →
  manual)    URL key)  keyword scan)   Haiku)      company+title)                          Sonnet)       Opus)     Obsidian)
```

1. **Intake** — feeds (Greenhouse/Lever/RSS) + manual URLs (`--url` flag and/or an inbox file) → raw listings.
2. **Dedup** (Python) — drop anything in the seen-index (keyed by URL hash).
3. **Hard-filter** (Python) — scan raw text for the blocklist before any agent spend.
4. **Extract** (agent, Haiku) — normalize survivors → structured fields including numeric comp (`comp_min`/`comp_max`/`comp_currency`/`comp_period`).
5. **Post-extract dedup** (Python) — fuzzy key `normalize(company) + normalize(title)` catches the same role via different URLs.
6. **Location** (Python) — apply remote/geo rules to the extracted location.
7. **Salary** (Python) — compare extracted comp (normalized to annual) against the floor; handle "not listed" per profile.
8. **Skill-gap** (agent, Sonnet) — compare résumé/skills to requirements.
9. **Score** (agent, Opus) — final fit judgment + rationale on the smallest surviving set.
10. **Publish** (Python) — write Obsidian note (score, gap, VEC fields).

Every stage implements one interface, `run(job) -> job`. Rejected jobs short-circuit but are logged so you can see *why* and tune your profile.

## Quickstart

**Prerequisites:** Python 3.11+, an Anthropic subscription (not API key — see below).

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Copy the example configs and fill them in:

```bash
cp config/profile.example.md config/profile.md
cp config/pipeline.example.yaml config/pipeline.yaml
$EDITOR config/profile.md       # paste your résumé, set salary_floor, blocklist, etc.
$EDITOR config/pipeline.yaml    # set your vault path, sources, inbox file
```

### Subscription billing guard

This project uses the **Claude Agent SDK with subscription auth** (OAuth token), *not* an API key. Before running, ensure `ANTHROPIC_API_KEY` is **unset** — if it is set, the SDK will bill against the API instead of your subscription and the runner will refuse to start.

```bash
unset ANTHROPIC_API_KEY   # must be absent
```

Log in to Claude Code so the SDK can pick up your subscription credentials:

```bash
claude login   # or: claude   # already logged in if you use Claude Code
```

### Run the pipeline

```bash
job-pipeline run                      # full run from configured sources
job-pipeline run --url https://...    # one-off URL (repeatable; works with sources too)
job-pipeline run --mock               # dry run using MockRunner — no tokens spent
job-pipeline run --url https://... --mock   # test a specific URL without spending tokens
```

Any URL passed via `--url` is processed this run only (not written to the inbox file). The
**inbox file** (`manual.inbox` in `pipeline.yaml`) accepts one URL per line — drop links in
from anywhere and they are consumed on the next successful run; errored lines stay in place
and retry automatically.

## Extensibility Seams

The pipeline has three seams designed to let you extend without touching core code:

### 1. Config-driven stages

`pipeline.yaml` lists stages by name, in order, with a model tier per agent stage:

```yaml
stages: [dedup, hard_filter, extract, dedup_fuzzy, location, salary, skill_gap, score, publish]
models: {extract: haiku, skill_gap: sonnet, score: opus}
```

Add, remove, or reorder stages with a config edit.

### 2. Pluggable sources, stages, and seeders via the registry

Three interfaces, each registered by name:

- **`Source`** (`fetch() -> list[Job]`) — yields raw job listings (Greenhouse, Lever, RSS, manual).
- **`Stage`** (`run(job) -> job`) — one processing step; may mark a job rejected with a reason.
- **`Seeder`** (`seed(seen_index) -> None`) — runs before intake to pre-populate the dedup index (e.g., `existing_vault` reads an existing Obsidian vault so already-tracked jobs are never re-surfaced).

Register a new adapter by name; core code is unchanged.

### 3. Personal data outside the repo

Your real `config/profile.md`, `config/pipeline.yaml`, vault path, and seen-index are gitignored. The repo ships `*.example` templates — publish-safe from day one.

`AgentRunner` is also swappable (SDK / mock / future `claude -p`) behind the same interface.

## VEC Note Semantics

Each published Obsidian note doubles as a Virginia Employment Commission (VEC) work-search record. The pipeline populates what it can from the listing (employer name, address, phone, position, source URL, discovery date). **Two fields you fill in yourself when you act:**

- `date_of_contact` — the date you actually applied, called, or emailed.
- `employer_contact_person` — the person you spoke/wrote to.
- `result_of_contact` — advances from `found` → `applied` → `interview` → …

The pipeline never fakes an application. Finding a listing is not a VEC contact. An Obsidian Dataview query over `date_of_contact` yields a VEC-ready weekly table.

VEC records must be retained ≥ 1 year; minimum two contacts per week.

**Skip-on-edit protection:** if you advance a note's `status` past `to_review` (i.e., you have acted on it), a subsequent `job-pipeline run` will not overwrite it. Use `--force` to override.

## Running Tests

```bash
# Full suite — no network, no tokens (MockRunner)
.venv/bin/pytest -v

# Opt-in real-SDK integration test (hits the Agent SDK; requires subscription auth and unset ANTHROPIC_API_KEY)
.venv/bin/pytest -m integration -v
```

The default `pytest` run excludes integration tests. All 68 rule/stage/orchestrator/store tests run in ~0.2 s.
