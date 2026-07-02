# Job Application Pipeline — Design Spec

**Date:** 2026-07-02
**Status:** Approved design, pre-implementation
**Owner:** Ryan

## 1. Purpose & Scope

A personal, extensible pipeline that discovers job listings, filters and scores them
against a personal profile, and publishes ranked matches as Obsidian notes that double
as Virginia Employment Commission (VEC) work-search records. **No automated applying.**

The project has two goals of equal weight:

1. **Product:** replace manual searching + evaluation with a repeatable pipeline; keep
   résumé tailoring manual.
2. **Method:** establish a reusable, cost-conscious orchestration pattern (a concrete
   pilot for adopting a standard agent-orchestration approach).

### In scope
- Hybrid intake: manual URLs (CLI `--url` + plaintext inbox file, one URL per line) + light
  pulls from API-friendly sources (Greenhouse, Lever, RSS).
- Deterministic Python orchestrator; agents only where judgment is required.
- Rule-based stages (dedup, hard-filter, fuzzy post-extract dedup, location, salary) in pure Python.
- Agent stages (extract, skill-gap, score) via the Claude Agent SDK.
- Publish to an Obsidian vault; each note is also a VEC work-search record.
- Opt-in `existing_vault` seeder that pre-populates the dedup index from an existing vault.
- Designed to be published (open-sourced) and personalized by others.

### Out of scope
- Automated applying (never).
- Migrating Ryan's *legacy* personal notes to the new schema — a one-time local script
  Ryan runs himself once the schema is locked. Not part of this framework.
- Third-party agent harnesses (e.g. pi.dev) — they draw on extra usage credits; this
  project stays first-party (Agent SDK / `claude -p`) to remain on the subscription pool.

## 2. Key Decisions & Rationale

- **Deterministic orchestrator + per-stage agents** (not Agent Teams, not all-agent).
  Agent Teams is all-Opus, heavier 5-hour-window burn, and overkill for a mostly-linear
  chain that needs no peer negotiation.
- **"Fat code, thin agents."** 5 of 8 filtering stages never touch a model; the 3 that do
  run on progressively smaller sets at escalating model tiers (Haiku → Sonnet → Opus).
  This is the core cost strategy and the project's demonstrable "what needs AI vs not"
  decision.
- **Agent SDK as the runner** (over headless `claude -p`). Same subscription billing, but
  more industry-relevant, better structured output, and unit-testable via a mock. Hidden
  behind an `AgentRunner` interface so `claude -p` or others can be swapped in.
- **Everything except the orchestrator is user-definable**, and the orchestrator itself is
  a swappable interface so an AI-based orchestrator can be slotted in later with zero
  stage changes.
- **Personal data lives outside the repo** (gitignored) with committed `*.example`
  templates — publish-safe from day one.

## 3. Architecture & Stage Ordering

Cheap deterministic filters run first, dropping jobs before any agent tokens are spent.

```
INTAKE ──▶ DEDUP ──▶ HARD-FILTER ──▶ EXTRACT ──▶ DEDUP-FUZZY ──▶ LOCATION ──▶ SALARY ──▶ SKILL-GAP ──▶ SCORE ──▶ PUBLISH
 (feeds +   (Python,  (Python,        (AGENT,     (Python,        (Python)     (Python)   (AGENT,       (AGENT,   (Python →
  manual)    URL key)  keyword scan)   Haiku)      company+title)                          Sonnet)       Opus)     Obsidian)
```

1. **Intake** — feeds (Greenhouse/Lever/RSS) + manual URLs (CLI `--url` and/or inbox file) → raw listings. Seeders (e.g. `existing_vault`) pre-populate the seen-index before intake.
2. **Dedup** (Python) — drop anything in the seen-index (keyed by URL hash). Free → first.
3. **Hard-filter** (Python) — scan *raw text* for the blocklist (crypto/web3/…) before any agent spend.
4. **Extract** (agent, cheap) — normalize survivors → structured fields, including numeric comp
   (`comp_min`/`comp_max`/`comp_currency`/`comp_period`). First AI spend, smallest set.
5. **Post-extract dedup** (Python) — second, nearly-free gate: fuzzy key
   `normalize(company) + normalize(title)` catches the same role reached via different URLs
   (cross-source duplicates) before further agent spend.
6. **Location** (Python) — apply remote/geo rules to the extracted location.
7. **Salary** (Python) — compare extracted `comp_min`/`comp_max` (normalized to annual) against
   the floor; handle "not listed" per profile.
8. **Skill-gap** (agent, mid) — compare résumé/skills to requirements.
9. **Score** (agent, strong) — final fit judgment + rationale, smallest set.
10. **Publish** (Python) — write Obsidian note (score, gap, VEC fields).

Every stage implements one interface, `run(job) -> job` (may mark the job rejected with a
reason). Rejected jobs short-circuit but are logged so the user can see *why* and tune the
profile.

## 4. Components & Project Structure

```
job_pipeline/                  # publishable framework (no personal data)
  core/
    job.py         # Job dataclass — fields accumulate as it flows
    stage.py       # Stage protocol + StageSpec descriptor
    pipeline.py    # wiring
    orchestrator.py# Orchestrator protocol + DeterministicOrchestrator (default)
    runner.py      # AgentRunner interface + SDK impl + MockRunner (tests)
    registry.py    # name→Stage / name→Source registries (extensibility seam)
  stages/          # dedup, hard_filter, extract, dedup_fuzzy, location, salary, skill_gap, score, publish
  sources/         # base + rss, greenhouse, lever, manual (CLI --url + inbox file)
  seeders/         # base + existing_vault (pre-populates seen-index; yields no jobs)
  store/
    seen_index.py  # dedup persistence (SQLite)
    obsidian.py    # vault note writer
  config.py        # loads pipeline config + profile
  cli.py           # `job-pipeline run` entrypoint

config/
  pipeline.example.yaml   # committed template
  profile.example.md      # committed template
tests/
pyproject.toml   README.md   LICENSE
```

**Three extensibility seams:**

1. **Config-driven pipeline** — `pipeline.yaml` lists stages by name, in order, with a model
   tier per agent stage. Add/remove/reorder = config edit.
2. **Pluggable sources, stages & seeders via the registry** — three interfaces, each registered
   by name: `Source` (yields jobs), `Stage` (`run(job) -> job`), `Seeder`
   (`seed(seen_index) -> None`, runs before intake). Extend by dropping in an adapter, core
   unchanged.
3. **Personal data outside the code** — real `profile.md`, `pipeline.yaml`, vault path, and
   seen-index are gitignored; repo ships `*.example` templates.

`AgentRunner` is swappable (SDK / mock / `claude -p`) behind the same interface.

## 5. Swappable Orchestrator (future AI orchestrator)

The orchestrator is an interface, and every stage exposes a self-describing spec so a future
AI orchestrator can reason over the catalog.

```python
class Orchestrator(Protocol):
    def run(self, jobs: list[Job], catalog: StageCatalog, ctx) -> list[Job]: ...

class DeterministicOrchestrator:   # default, ships now — walks pipeline.yaml order, short-circuits rejects
class AgentOrchestrator:           # future drop-in — LLM loop that dynamically routes using the catalog

@dataclass
class StageSpec:
    name: str
    purpose: str                 # human/LLM-readable
    requires: list[str]          # Job fields needed  e.g. ["raw_text"]
    produces: list[str]          # Job fields set      e.g. ["rejected", "reject_reason"]
    kind: Literal["deterministic", "agent"]
    cost_tier: Literal["free", "cheap", "mid", "expensive"]
```

A `StageSpec` is effectively a tool-definition for an LLM. The deterministic orchestrator
ignores most of it; an `AgentOrchestrator` uses it (plus each job's `trace`) to route
dynamically — skip `skill_gap` when intent is clear, re-run `extract` on empty fields,
branch on ambiguity.

Supporting requirements so the swap is truly drop-in:
- **`Job.trace`** — append-only `(stage, verdict, timestamp)` log. Audit trail today, AI state tomorrow.
- Stages stay **pure and idempotent** — safe to call in any order the orchestrator picks.

## 6. Data Model & Schemas

### `Job` dataclass
```python
@dataclass
class Job:
    # intake
    source: str; url: str; raw_text: str; fetched_at: datetime
    id: str                        # stable hash(url) → primary dedup key
    # after extract (agent)
    title: str; company: str; location: str
    comp_text: str                 # verbatim comp string, for display
    comp_min: int | None; comp_max: int | None      # numeric, parsed by the extract agent
    comp_currency: str | None; comp_period: str | None   # e.g. "USD", "annual" | "hourly"
    fuzzy_key: str                 # normalize(company) + normalize(title) — cross-source dedup
    requirements: list[str]; description: str
    employer_address: str; employer_phone: str; employer_email: str   # VEC, if present
    # after rule stages
    location_ok: bool | None; salary_ok: bool | None
    # after agent stages
    skill_gap: dict                # have / missing / partial
    score: float; score_rationale: str
    # bookkeeping
    trace: list[tuple]             # (stage, verdict, timestamp)
    rejected: bool = False
    reject_reason: str | None = None
    reject_stage: str | None = None
    errored: bool = False
    error: str | None = None
```

### `profile.md` (single file; YAML frontmatter = hard rules, prose = résumé + fuzzy prefs)
```yaml
---
salary_floor: 140000
locations: { remote: true, allowed_metros: ["Richmond, VA"] }
blocklist: [crypto, web3, blockchain, defi]
must_have_skills: [python, distributed systems]
nice_to_have: [rust, k8s]
salary_not_listed: keep      # keep | reject
---
## Base résumé
<prose the skill-gap + score agents read>
## What I'm looking for
<fuzzy preferences the score agent weighs>
```

### `pipeline.yaml`
```yaml
sources:
  - {type: greenhouse, board: acme}
  - {type: rss, url: "https://..."}
  - {type: manual, inbox: ~/vault/jobs/inbox.txt}   # one URL per line; consumed on run
seeders:
  - {type: existing_vault, path: ~/vault/jobs, url_field: source_url}   # opt-in dedup seed
stages: [dedup, hard_filter, extract, dedup_fuzzy, location, salary, skill_gap, score, publish]
models: { extract: haiku, skill_gap: sonnet, score: opus }
output: { vault: ~/vault/jobs, keep_rejects: true }
limits: { max_agent_jobs_per_run: 40 }   # overflow: FIFO; deferred jobs stay unseen → retry next run
```

Manual URLs enter two ways, both handled by the `manual` source: `job-pipeline run --url <...>`
(repeatable, one-off) and the configured **inbox file** — plaintext, one URL per line, dump links
in from anywhere. Processed lines are removed on a successful run (the file acts as a queue);
lines for jobs that error stay in place and retry.

### Obsidian note (publish output; frontmatter doubles as the VEC record)
```markdown
---
company: "Acme Corp"
position: "Senior Backend Engineer"
employer_address: "..."          # VEC
employer_phone: "..."            # VEC (fax/email/web also captured if present)
employer_contact_person: ""      # VEC — user fills on apply
date_found: 2026-07-02           # pipeline discovery date (not a VEC contact)
date_of_contact: ""              # VEC date of contact — user fills on apply
source_url: "https://..."        # VEC web address
type_of_work: "Senior Backend Engineer"   # VEC
result_of_contact: "found"       # VEC — found → applied → interview → ...
score: 87
status: to_review
---
## Fit — 87/100
<score rationale>
## Skill gap
- Have: ...  | Missing: ...  | Partial: ...
## Description
<extracted summary>
```

**VEC requirements captured** (verified against VEC guidance): date of contact; employer
name, full address, phone (plus fax/email/web when available); person spoken with; type of
work/position; result of contact. Records must be retained ≥1 year; minimum two contacts per
week. The pipeline never fakes an application — finding a listing is *not* a VEC contact, so
`date_of_contact`, `employer_contact_person`, and `result_of_contact` advance only when the user
acts (applies). Note frontmatter is designed so an Obsidian Dataview query over `date_of_contact`
yields a VEC-ready weekly table.

## 7. Existing-Vault Seeder

`existing_vault` is a generic, opt-in **`Seeder`** (`seed(seen_index) -> None`) — a third
pluggable kind alongside `Source` and `Stage`, since it yields no jobs. It reads a configured
vault, extracts a URL (and/or company+title fuzzy key) from each note's frontmatter via a field
mapping, and pre-populates the seen-index before intake so already-tracked jobs are never
re-surfaced. Generic and publish-safe (benefits anyone with an Obsidian job vault). Ryan's own
legacy-note reformatting is a separate local step, not part of this framework.

## 8. Error Handling

- **Fail fast on config.** Validate `profile.md` frontmatter + `pipeline.yaml` (pydantic) at
  startup, before any fetch or token spend.
- **Per-job isolation.** Each job's stage walk is wrapped; an unhandled exception marks the job
  `errored` (distinct from `rejected`) with stage + message, logs, and the run continues.
- **Agent-stage resilience.** Retries with backoff + timeout; structured output validated against
  a pydantic schema; parse failure after retries → `errored`, downstream skipped.
- **Source resilience.** Each source fetch is independently guarded; a dead feed warns, others flow.
- **Idempotent publish.** Notes keyed by `Job.id`; if a note exists and `status` was advanced past
  `to_review`, publish skips (protecting manual edits); `--force` overrides.
- **Seen-index integrity.** A job is marked seen only on terminal reject or successful publish;
  `errored` jobs stay unseen and retry next run (transient failures self-heal).
- **Window-burn guard.** `limits.max_agent_jobs_per_run` caps how many jobs reach agent stages per
  run; cheap filters still process everything. Overflow is FIFO (intake order): deferred jobs are
  not marked seen, so they retry next run, and the run summary reports the deferred count — a
  capped run never silently looks complete.
- **Inbox-file integrity.** The manual inbox is consumed transactionally: a line is removed only
  when its job reaches a terminal state (published or rejected); errored/deferred lines remain.

## 9. Testing (TDD; suite uses no tokens, no network)

- **Rule stages** — pure unit tests over `Job` fixtures; exhaustive edge cases (salary "not
  listed", hourly→annual normalization, remote rules, blocklist word-boundaries, fuzzy-key
  normalization for cross-source dedup).
- **Agent stages** — `MockRunner` returns canned structured output; assert mapping onto `Job` and
  verdicts, no real calls.
- **Orchestrator** — fake stages verify ordering, short-circuit, error isolation.
- **Sources** — saved RSS/Greenhouse/Lever fixtures → parsed `Job` list; `manual` against a temp
  inbox file (incl. consume-on-terminal-state); `existing_vault` seeder against a temp vault.
- **Store** — Obsidian writer against a temp dir (incl. skip-on-edit idempotency); seen-index against
  temp SQLite.
- **End-to-end** — fake source + `MockRunner` + temp vault → full deterministic run.
- **Real SDK calls** — separate, opt-in, marked integration test (not in default suite).

## 10. Open Items for Implementation Planning

- Confirm the Agent SDK subscription-auth setup (OAuth token) and how per-stage model selection is
  passed. Billing terms are volatile — verify at build time.
- Confirm structured-output mechanism in the SDK (tool/schema) for extract/skill-gap/score.
- Decide the SQLite schema for the seen-index and where it lives (config).
- Pin source adapters for the first cut (likely Greenhouse + Lever + RSS + manual + existing_vault).
