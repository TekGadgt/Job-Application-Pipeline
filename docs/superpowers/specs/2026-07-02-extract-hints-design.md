# Per-Source Extract Hints — Design Spec

**Date:** 2026-07-02
**Status:** Approved for planning
**Scope:** Small. One new optional yaml key, one Job field, one wrapper class, one prompt slot. This is the only change needed to make the HN "Who is hiring?" feed work well — the existing `rss` source already ingests https://hnrss.org/whoishiring/jobs (full comment HTML in the entry body); the extract agent just needs to be told what it's looking at.

## Goal

Let a source entry in `pipeline.yaml` carry a free-text hint that is prepended to the extract prompt for every job from that source, so loosely formatted listings (HN comments, scraped pages) extract as reliably as clean ATS postings — without per-source extractor code.

## Config Syntax (binding)

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

`extract_hint` is valid on **any** source type (rss, greenhouse, lever, manual, scrape). Optional; absent means today's behavior, byte-for-byte identical prompts.

## Design

### 1. `Job.extract_hint: str = ""` (core/job.py)

Data rides on the job like everything else stages consume. Not written to frontmatter, not traced.

### 2. `HintedSource` wrapper (sources/base.py)

Sources stay ignorant of hints — no edits to any existing source class. A small delegating wrapper satisfies the `Source` protocol:

```python
class HintedSource:
    def __init__(self, inner: Source, hint: str) -> None: ...
    def fetch(self) -> list[Job]:        # inner.fetch(), stamp job.extract_hint
    def on_terminal(self, job) -> None:  # delegate to inner
```

`build_sources` (core/pipeline.py) pops `extract_hint` from each source spec dict before constructing the source (so constructors never see it), and wraps when non-empty. Note: `run_pipeline`'s `origin` map then holds the wrapper, whose `on_terminal` delegates — manual-inbox consumption semantics are unchanged.

### 3. Extract prompt slot (stages/agents — extract module)

`EXTRACT_PROMPT` gains a `{source_context}` slot at the top:

```
{source_context}Extract structured fields from this job listing. ...
```

`ExtractStage.run` fills it with `f"SOURCE CONTEXT: {job.extract_hint}\n\n"` when the hint is non-empty, else `""` — via the existing brace-safe `_fill`, which leaves scraped `{}` in hints harmless. Prompt constant stays frozen; the filled prefix is stable per source, so prompt-cache behavior is unchanged within a run.

## Coordination With In-Flight Specs

- **Stage package refactor** (2026-07-02): if that lands first, the prompt edit goes in `stages/agents/extract.py`; otherwise `stages/agents.py`. No conflict either way.
- **Scrape source** (2026-07-02): `extract_hint` composes for free — `build_sources` wraps scrape sources like any other. No changes to that spec.

## Testing

- `build_sources`: spec with `extract_hint` → wrapped source, hint stamped on fetched jobs; spec without → bare source, `extract_hint == ""`; constructor never receives the key (a source class with no `extract_hint` kwarg must not raise).
- `HintedSource.on_terminal` delegates (assert against a recording fake).
- `ExtractStage`: hint present → prompt starts with `SOURCE CONTEXT:` and contains the hint verbatim (braces included); hint absent → prompt identical to the current constant's fill.
- e2e example yaml parses with the new key.

## Acceptance

- `pipeline.example.yaml` gains the HN entry above (commented out).
- README: one short subsection "Loosely formatted feeds (e.g. HN Who is hiring?)" showing the yaml.

## Non-Goals

- No per-source reply schemas, models, or stage lists — hints steer the prompt, nothing else.
- No HN-specific source class, month-thread logic, or comment splitting (one comment = one job; multi-role comments are handled by the hint text, not code).
- No hint support for skill_gap/score prompts (extract is where format variance lives).
