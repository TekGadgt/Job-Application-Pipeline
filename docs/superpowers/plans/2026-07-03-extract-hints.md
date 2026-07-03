# Per-Source Extract Hints Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a `pipeline.yaml` source entry carry a free-text `extract_hint` that is prepended to the extract prompt for every job from that source, so loosely formatted feeds (HN "Who is hiring?") extract as reliably as clean ATS postings.

**Architecture:** The hint rides on the `Job` (new `extract_hint` field). A `HintedSource` wrapper stamps the hint onto fetched jobs so no existing source class changes; `build_sources` pops the key from the spec dict and wraps when the hint is non-empty. The extract prompt gains a `{source_context}` slot filled with `SOURCE CONTEXT: <hint>` (or `""`) via the existing single-pass, brace-safe `_fill`.

**Tech Stack:** Python ≥3.11, pydantic, pytest. No new dependencies.

## Global Constraints

- Package is `job_pipeline`; Python ≥3.11.
- Tests spend **no** model tokens and make **no** network calls (use `MockRunner` and fakes); no real personal data in fixtures.
- `extract_hint` is valid on **any** source type; it is **optional**. When absent, the extract prompt is **byte-for-byte identical to today's** output.
- Hints steer **only** the extract prompt — never `skill_gap` or `score`, no per-source models/schemas/stage lists.
- Do **not** modify `job_pipeline/config.py`: `PipelineConfig.sources` is `list[dict]`, so an extra `extract_hint` key rides along freely with no schema change.
- `_fill` is already single-pass and brace-safe (regex over the template only); do not reintroduce sequential `str.replace`. Values (hint, raw_text) are never rescanned, so a hint containing `{...}` is safe.
- No HN-specific source class, month-thread logic, or comment splitting.

---

### Task 1: Hint plumbing — `Job.extract_hint`, `HintedSource`, `build_sources` wiring

**Files:**
- Modify: `job_pipeline/core/job.py` (add field after `id`)
- Modify: `job_pipeline/sources/base.py` (add `HintedSource` class)
- Modify: `job_pipeline/core/pipeline.py` (import `HintedSource`; update `build_sources`, currently lines 56-68)
- Test: `tests/test_sources.py` (HintedSource unit test), `tests/test_build_sources.py` (new — build_sources wiring)

**Interfaces:**
- Consumes: existing `Source` protocol and `Job` dataclass in `job_pipeline/sources/base.py`; `PipelineConfig`, `OutputConfig`, `get_source` in `job_pipeline/core/pipeline.py`.
- Produces:
  - `Job.extract_hint: str = ""` — a public dataclass field, default empty.
  - `HintedSource(inner: Source, hint: str)` in `job_pipeline/sources/base.py` with `fetch() -> list[Job]` (stamps `job.extract_hint = self.hint` on every fetched job) and `on_terminal(job) -> None` (delegates to `inner.on_terminal(job)`). Task 2's extract stage reads `job.extract_hint`.
  - `build_sources` pops `extract_hint` from each source spec dict before constructing the source, and wraps the constructed source in `HintedSource` when the hint is non-empty.

- [ ] **Step 1: Confirm the green baseline**

Run: `.venv/bin/pytest -q`
Expected: `73 passed, 1 deselected`

- [ ] **Step 2: Write the failing HintedSource unit test**

In `tests/test_sources.py`, add the `Job` import to the existing imports at the top:

```python
from job_pipeline.core.job import Job
```

Then append this test:

```python
def test_hinted_source_stamps_hint_and_delegates_terminal():
    from datetime import datetime, UTC
    from job_pipeline.sources.base import HintedSource

    class RecordingSource:
        def __init__(self):
            self.terminal = []
        def fetch(self):
            return [Job(source="t", url="https://x.com/1", raw_text="r",
                        fetched_at=datetime.now(UTC))]
        def on_terminal(self, job):
            self.terminal.append(job.url)

    inner = RecordingSource()
    src = HintedSource(inner, "HINT TEXT")
    jobs = src.fetch()
    assert jobs[0].extract_hint == "HINT TEXT"
    src.on_terminal(jobs[0])
    assert inner.terminal == ["https://x.com/1"]      # delegated, not swallowed
```

- [ ] **Step 3: Run it to verify it fails**

Run: `.venv/bin/pytest tests/test_sources.py::test_hinted_source_stamps_hint_and_delegates_terminal -v`
Expected: FAIL — `ImportError: cannot import name 'HintedSource'` (and `Job` has no `extract_hint` attribute).

- [ ] **Step 4: Add the `Job.extract_hint` field**

In `job_pipeline/core/job.py`, add the field immediately after the `id` line (line 16). The intake block becomes:

```python
    fetched_at: datetime
    id: str = ""                       # stable hash(url) — primary dedup key
    extract_hint: str = ""             # per-source hint prepended to the extract prompt
    # after extract (agent)
    title: str = ""
```

- [ ] **Step 5: Add the `HintedSource` wrapper**

In `job_pipeline/sources/base.py`, append after `http_get_json`:

```python
class HintedSource:
    """Wraps a source, stamping a per-source extract hint onto every fetched job.

    Existing source classes stay ignorant of hints; the wrapper satisfies the
    same Source protocol and delegates on_terminal so inbox-consumption
    semantics are unchanged.
    """

    def __init__(self, inner: Source, hint: str) -> None:
        self.inner = inner
        self.hint = hint

    def fetch(self) -> list[Job]:
        jobs = self.inner.fetch()
        for job in jobs:
            job.extract_hint = self.hint
        return jobs

    def on_terminal(self, job: Job) -> None:
        self.inner.on_terminal(job)
```

- [ ] **Step 6: Run the HintedSource test to verify it passes**

Run: `.venv/bin/pytest tests/test_sources.py::test_hinted_source_stamps_hint_and_delegates_terminal -v`
Expected: PASS

- [ ] **Step 7: Write the failing build_sources tests**

Create `tests/test_build_sources.py`:

```python
from job_pipeline.config import PipelineConfig, OutputConfig
from job_pipeline.core.pipeline import build_sources
from job_pipeline.sources.base import HintedSource
from job_pipeline.sources.feeds import RssSource


def _cfg(source_spec, tmp_path):
    return PipelineConfig(
        sources=[source_spec],
        stages=["dedup"],
        output=OutputConfig(vault=tmp_path / "vault"),
    )


def test_build_sources_wraps_and_pops_hint_key(tmp_path):
    # extract_hint must be popped before construction: RssSource(url=...) would
    # raise TypeError if handed an unexpected extract_hint kwarg.
    cfg = _cfg({"type": "rss", "url": "https://h/x.rss",
                "extract_hint": "free-form HN comment"}, tmp_path)
    sources = build_sources(cfg)
    assert len(sources) == 1
    assert isinstance(sources[0], HintedSource)
    assert isinstance(sources[0].inner, RssSource)
    assert sources[0].hint == "free-form HN comment"


def test_build_sources_leaves_source_bare_without_hint(tmp_path):
    cfg = _cfg({"type": "rss", "url": "https://h/x.rss"}, tmp_path)
    sources = build_sources(cfg)
    assert len(sources) == 1
    assert isinstance(sources[0], RssSource)      # not wrapped
```

- [ ] **Step 8: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_build_sources.py -v`
Expected: FAIL — the wrapping test raises `TypeError: __init__() got an unexpected keyword argument 'extract_hint'` (the key is not yet popped), and `HintedSource` wrapping is absent.

- [ ] **Step 9: Update `build_sources`**

In `job_pipeline/core/pipeline.py`, add the import alongside the other `job_pipeline.sources` imports near the top of the file:

```python
from job_pipeline.sources.base import HintedSource
```

Replace the `build_sources` function body (currently lines 56-68) with:

```python
def build_sources(cfg: PipelineConfig, extra_urls: list[str] | None = None):
    sources = []
    manual_seen = False
    for spec in cfg.sources:
        spec = dict(spec)
        kind = spec.pop("type")
        hint = spec.pop("extract_hint", "")
        if kind == "manual":
            spec["urls"] = extra_urls or []
            manual_seen = True
        source = get_source(kind)(**spec)
        sources.append(HintedSource(source, hint) if hint else source)
    if extra_urls and not manual_seen:
        sources.append(get_source("manual")(urls=extra_urls))
    return sources
```

- [ ] **Step 10: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `76 passed, 1 deselected` (73 prior + 3 new; the HintedSource test and 2 build_sources tests).

- [ ] **Step 11: Commit**

```bash
git add job_pipeline/core/job.py job_pipeline/sources/base.py job_pipeline/core/pipeline.py tests/test_sources.py tests/test_build_sources.py
git commit -m "feat: extract_hint plumbing — Job field, HintedSource wrapper, build_sources wiring"
```

---

### Task 2: Extract prompt slot + docs

**Files:**
- Modify: `job_pipeline/stages/agents/extract.py` (prompt constant + `ExtractStage.run`)
- Modify: `config/pipeline.example.yaml` (commented-out HN entry)
- Modify: `README.md` (new subsection before `## VEC Note Semantics`)
- Test: `tests/test_agent_stages.py`

**Interfaces:**
- Consumes: `Job.extract_hint` (from Task 1); the existing `_fill` from `job_pipeline/stages/agents/common.py` (single-pass, leaves unknown `{tokens}` intact — so the stage MUST always pass `source_context`, empty string when no hint).
- Produces: extract prompts that begin with `SOURCE CONTEXT: <hint>\n\n` when `job.extract_hint` is non-empty, and are byte-for-byte identical to today when it is empty.

- [ ] **Step 1: Write the failing prompt tests**

In `tests/test_agent_stages.py`, append:

```python
def test_extract_prepends_source_context_when_hint_present():
    r = MockRunner([EXTRACT_REPLY])
    # Hint contains a brace token to pin brace-safe composition (verbatim, no splice).
    ExtractStage(r, "haiku").run(make_job(extract_hint="HN comment; fields like {company}"))
    prompt = r.calls[0][0]
    assert prompt.startswith("SOURCE CONTEXT: HN comment; fields like {company}\n\n")
    assert "Senior Eng at Acme" in prompt        # raw_text still present


def test_extract_omits_source_context_when_no_hint():
    r = MockRunner([EXTRACT_REPLY])
    ExtractStage(r, "haiku").run(make_job())      # no hint
    prompt = r.calls[0][0]
    assert "SOURCE CONTEXT" not in prompt
    assert prompt.startswith("Extract structured fields from this job listing.")
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/pytest tests/test_agent_stages.py::test_extract_prepends_source_context_when_hint_present tests/test_agent_stages.py::test_extract_omits_source_context_when_no_hint -v`
Expected: FAIL — with hint present the prompt still starts with "Extract structured…" (no slot yet), so the `startswith("SOURCE CONTEXT…")` assertion fails.

- [ ] **Step 3: Add the `{source_context}` slot and fill it**

In `job_pipeline/stages/agents/extract.py`, change the first line of `EXTRACT_PROMPT` to prepend the slot (everything else in the constant is unchanged):

```python
EXTRACT_PROMPT = """{source_context}Extract structured fields from this job listing. Reply with ONLY a JSON object:
{"title": str, "company": str, "location": str, "comp_text": str,
 "comp_min": int|null, "comp_max": int|null, "comp_currency": str|null,
 "comp_period": "annual"|"hourly"|null, "requirements": [str], "description": str,
 "employer_address": str, "employer_phone": str, "employer_email": str}
comp_min/comp_max are numbers only (e.g. "$150k" -> 150000). Use "" / null / [] when absent.
description is a 2-3 sentence summary.

LISTING:
{raw_text}"""
```

Replace `ExtractStage.run` with:

```python
    def run(self, job: Job) -> Job:
        source_context = (
            f"SOURCE CONTEXT: {job.extract_hint}\n\n" if job.extract_hint else ""
        )
        reply = self.runner.run(
            _fill(EXTRACT_PROMPT, source_context=source_context, raw_text=job.raw_text),
            self.model, ExtractReply,
        )
        for field_name, value in reply.model_dump().items():
            setattr(job, field_name, value)
        job.add_trace("extract", "extracted")
        return job
```

- [ ] **Step 4: Run the prompt tests to verify they pass**

Run: `.venv/bin/pytest tests/test_agent_stages.py::test_extract_prepends_source_context_when_hint_present tests/test_agent_stages.py::test_extract_omits_source_context_when_no_hint -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/pytest -q`
Expected: `78 passed, 1 deselected` (76 after Task 1 + 2 new). Existing extract tests (`test_extract_maps_reply_onto_job`, `test_extract_tolerates_braces_in_raw_text`) still pass — the empty-hint path leaves their prompts unchanged.

- [ ] **Step 6: Add the commented-out HN entry to the example config**

In `config/pipeline.example.yaml`, under the `sources:` list, add these fully-commented lines after the `manual` entry (fully commented so YAML parsing is unaffected):

```yaml
  # Loosely formatted feed — HN "Who is hiring?" (uncomment to enable):
  # - type: rss
  #   url: "https://hnrss.org/whoishiring/jobs"
  #   extract_hint: >
  #     This is a free-form Hacker News "Who is hiring?" comment, not a formal
  #     posting. Conventions: REMOTE/ONSITE/HYBRID flags, "Company | Role |
  #     Location" pipe-separated first lines, salary often absent. If one
  #     comment advertises several roles, extract the single best-matching role
  #     and mention the others in the description.
```

- [ ] **Step 7: Verify the example config still parses**

Run: `.venv/bin/python -c "from job_pipeline.config import load_pipeline_config; c = load_pipeline_config('config/pipeline.example.yaml'); print(len(c.sources), 'sources')"`
Expected: prints `4 sources` (the HN entry is commented out, so the count is unchanged) with no exception.

- [ ] **Step 8: Add the README subsection**

In `README.md`, insert this subsection immediately before the `## VEC Note Semantics` heading (i.e., after the `AgentRunner is also swappable…` line that ends the Extensibility Seams section):

```markdown
### Loosely formatted feeds (e.g. HN "Who is hiring?")

Some feeds aren't clean ATS postings. The Hacker News "Who is hiring?" RSS feed,
for example, is free-form comments. Add an `extract_hint` to any source and it is
prepended to the extract prompt for every job from that source — no per-source
code needed:

```yaml
sources:
  - type: rss
    url: "https://hnrss.org/whoishiring/jobs"
    extract_hint: >
      This is a free-form Hacker News "Who is hiring?" comment, not a formal
      posting. Conventions: REMOTE/ONSITE/HYBRID flags, "Company | Role |
      Location" pipe-separated first lines, salary often absent. If one
      comment advertises several roles, extract the single best-matching role
      and mention the others in the description.
```

`extract_hint` is optional and valid on any source type. Without it, prompts are
unchanged.
```

- [ ] **Step 9: Commit**

```bash
git add job_pipeline/stages/agents/extract.py config/pipeline.example.yaml README.md tests/test_agent_stages.py
git commit -m "feat: extract prompt source_context slot + HN who-is-hiring docs"
```

---

## Verification (whole plan)

- `.venv/bin/pytest -q` → `78 passed, 1 deselected`
- `.venv/bin/python -c "from job_pipeline.config import load_pipeline_config; load_pipeline_config('config/pipeline.example.yaml')"` → no error
- Manual sanity: a `Job(extract_hint="")` produces an extract prompt starting with `Extract structured fields` (byte-for-byte identical to pre-change); a non-empty hint produces one starting with `SOURCE CONTEXT:`.
