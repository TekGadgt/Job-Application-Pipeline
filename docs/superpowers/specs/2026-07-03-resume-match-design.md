# Resume Match Stage — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Motivation:** Ryan maintains several role-targeted resumes (DevEx, DevRel, IC). "Which resume do I send?" is a per-application decision the pipeline already has all the inputs for: the extracted job, the skill gap, and the resumes themselves. This stage answers it in the published note.

## Goal

An **optional** agent stage, `resume_match`, that weighs a set of labeled resumes against a job and records: a per-resume fit rating, the recommended resume, the rationale, and — when nothing fits well — a suggestion to tailor a custom resume with concrete advice. Users without multiple resumes simply don't list the stage; nothing changes for them.

**Hard boundary:** the pipeline recommends and advises; it never *generates or edits* a resume. Auto-tailored documents drift toward the automated-applying line this project refuses to cross.

## Config Syntax (binding)

### profile.md frontmatter

```yaml
resumes:
  devex:  {file: devex.md,  covers: "Forward Deployed Engineer, Developer Success Engineer",
           link: resume_pdfs/devex/resume.pdf}
  devrel: {file: devrel.md, covers: "Developer Advocate",
           link: resume_pdfs/devrel/resume.pdf}
  ic:     {file: ic.md,     covers: "All IC roles, e.g. Senior Software Engineer",
           link: resume_pdfs/ic/resume.pdf}
```

- Keys are the labels used everywhere downstream (frontmatter, notes, prompts).
- `file` resolves **relative to profile.md's parent folder** (absolute paths also allowed); each file is a plain markdown resume — a real document you also actually send.
- `covers` is a short free-text routing description shown to the agent.
- `link` (optional) is the **vault-internal path of the deliverable resume** (typically the PDF you actually submit) as Obsidian resolves it. Never read by the pipeline, never sent to the agent — it exists solely so published notes can wiki-link the recommended resume (see Publish). Absent → no link rendered, everything else unchanged.
- Loaded fail-fast in `load_profile`: a missing/unreadable resume file raises `ValueError` naming the label and resolved path. `resumes:` absent → `{}`, today's behavior.
- The profile **body is unchanged** in meaning: general background + preferences, still the only profile input to `skill_gap` and `score`.

### pipeline.yaml

```yaml
stages: [dedup, hard_filter, extract, dedup_fuzzy, location, salary, skill_gap, resume_match, score, publish]
models: {extract: haiku, skill_gap: sonnet, resume_match: sonnet, score: opus}
```

Canonical position: after `skill_gap` (its output is an input here), before `score`. The example yaml ships with `resume_match` **commented out** in both lines.

## Design

### 1. Profile model (config.py)

```python
class ResumeRef(BaseModel):
    file: str
    covers: str = ""
    link: str = ""      # vault-internal path to the deliverable (PDF); publish-only
    body: str = ""      # populated by load_profile, never from yaml

class Profile(BaseModel):
    ...
    resumes: dict[str, ResumeRef] = {}
```

`load_profile` reads each `file` and fills `body`. Label order in the mapping is preserved (dicts are ordered) and used for prompt rendering.

### 2. Job fields (core/job.py)

```python
recommended_resume: str = ""       # label from profile.resumes
resume_match: dict = {}            # full reply: ratings, rationale, custom advice
```

### 3. The stage (stages/agents/resume_match.py)

`ResumeMatchStage`, `@register_stage("resume_match")`, StageSpec: purpose "recommend which labeled resume to submit", requires `["title", "description", "skill_gap"]`, produces `["recommended_resume", "resume_match"]`, kind `agent`, cost_tier `mid`.

Constructor `(runner, model, profile)` — same convention as `skill_gap`/`score` today; when the multi-provider-runners spec (2026-07-02) lands and changes agent-stage constructors to chains, this stage follows the same convention as its siblings.

**Fail-fast:** `__init__` raises `ValueError("resume_match stage requires resumes: in profile.md frontmatter")` if `profile.resumes` is empty. Misconfiguration dies at build time, before any fetching or tokens.

Reply schema:

```python
class ResumeFit(BaseModel):
    label: str
    fit: float = Field(ge=0, le=100)
    reason: str

class ResumeMatchReply(BaseModel):
    ratings: list[ResumeFit]
    recommended: str
    custom_suggested: bool = False
    custom_advice: str = ""        # 2-3 bullets: what a tailored resume should emphasize
```

Prompt (frozen constant, filled via `_fill`): job title/company/location/description, the skill-gap dict, then each resume rendered as `### <label> (covers: <covers>)` followed by its full body. Instructions: rate every resume 0-100 for *this job*, pick the best label, and if none fits well (all ratings below ~60) set `custom_suggested` with concrete advice. Full resume texts are sent — sonnet-tier cost, only on jobs that survived every free filter; summarization is premature optimization at personal volume.

**Defensive validation in `run`:** if `reply.recommended` is not a configured label, fall back to the highest-rated valid label and add a trace noting the correction (`"agent recommended unknown label X; using Y"`). Never errors the job over a mislabel. `job.resume_match` stores `reply.model_dump()`; `job.recommended_resume` stores the (validated) label. Trace: `("resume_match", "recommended <label>")`.

### 4. Publish (store/obsidian.py / stages/publish.py)

Only when `job.resume_match` is non-empty (stage ran):

- Frontmatter gains `recommended_resume: <label>` and `resume_submitted: ""` — the latter user-filled when you actually apply, mirroring the VEC `date_of_contact` pattern, so your records show which resume went out.
- When the recommended resume has a `link`, frontmatter also gains `recommended_resume_link: "[[<link>|<label>]]"` — the same wiki-link convention as a hand-maintained tracker, clickable straight to the PDF. `recommended_resume` stays the bare label (Dataview-friendly); the link is a separate key, omitted when `link` is unset. (`resume_submitted` remains free text; paste the wikilink there if you submitted a different one.)
- Body gains a `## Resume Match` section: one line per rating (`- **devex** (72/100): <reason>`), the recommendation — rendered as `[[<link>|<label>]]` when a link is configured, bare label otherwise — and, when `custom_suggested`, a `> [!tip] Consider a tailored resume` callout containing `custom_advice`.

When the stage didn't run, notes are **byte-identical to today** (existing publish tests unchanged).

## Coordination With In-Flight Specs

- **Multi-provider runners** (2026-07-02): whichever lands first, the other adapts mechanically — this stage's constructor follows the prevailing agent-stage convention.
- **Observability** (2026-07-03): `run_jobs` rows need no schema change; the recommendation is visible in the note and in `Job.trace`.
- **Local server/UI** (2026-07-03): recommended resume can surface in the job drill-down later; no change to that spec now.

## Testing (no network, no tokens)

- Profile loading: relative + absolute `file` resolution; `body` populated; missing file raises naming label and path; absent `resumes:` → `{}` and existing profile fixtures still load.
- Stage: MockRunner reply → fields set, trace added; prompt contains every label, `covers`, and full resume bodies — and never any `link` value; unknown `recommended` falls back to highest-rated valid label with correction trace; empty `profile.resumes` → `ValueError` at construction.
- Wiring: `build_stages` constructs the stage from `models["resume_match"]`; stage listed without `resumes:` in profile fails at build, not mid-run.
- Publish: with `resume_match` populated → frontmatter keys + section rendered (including the custom-advice callout); recommended resume with `link` → `recommended_resume_link` wikilink key + linked body line, without `link` → no link key, bare label; without `resume_match` → note byte-identical to current fixtures.
- e2e: full MockRunner run with the stage in the list → published note carries the recommendation.

## Acceptance

- `config/profile.example.md` gains a commented `resumes:` block (the three-label example above).
- `config/pipeline.example.yaml` shows `resume_match` commented out in `stages:` and `models:`.
- README: subsection "Multiple resumes" under Extensibility Seams — the frontmatter syntax, where files live, what the note shows, and the no-generation boundary stated explicitly.

## Non-Goals

- No resume generation, editing, or file output of any kind.
- No per-resume `skill_gap`/`score` runs (one resume-match call total, not N).
- No swapping the score stage's profile input based on the recommendation.
- No resume content in the seen-index or run history.
- No minimum-fit config knob (the ~60 guidance lives in the prompt; tune by editing it).
