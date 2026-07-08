# Stage Dependency Injection (StageContext) — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Motivation:** The deepest remaining modularity gap. `build_stages` wires every stage through a hardcoded name-keyed lambda dict in core (`core/pipeline.py:38-48`). The README promises "register a stage, list it in yaml" — but that's only true for dependency-free stages. A custom stage needing the profile, the seen index, or a runner requires **editing core**, which defeats the registry. Found during the 2026-07-03 whole-repo modularity review.

## Goal

Stages declare their own construction. Core stops knowing stage names: `build_stages` becomes a uniform loop with zero per-stage knowledge, and a fork's stage gets any pipeline dependency without touching `job_pipeline/core/`.

## Design

### 1. `StageContext` (core/stage.py)

A frozen dataclass bundling everything a stage may legitimately need at build time:

```python
@dataclass(frozen=True)
class StageContext:
    profile: Profile
    seen: StateStore            # protocol from the store-backends spec (or SeenIndex until it lands)
    publisher: Publisher        # same
    runner: AgentRunner         # or per-stage chain resolution — see Coordination
    models: dict                # cfg.models (per-stage model config)
    force: bool
```

### 2. Construction convention (binding)

Every registered stage class provides a classmethod:

```python
@classmethod
def from_context(cls, ctx: StageContext) -> "Stage": ...
```

- Built-in examples: `DedupStage.from_context` → `cls(ctx.seen)`; `HardFilterStage` → `cls(ctx.profile)`; `ExtractStage` → `cls(ctx.runner, ctx.models["extract"])`; `PublishStage` → `cls(ctx.publisher, ctx.force)`.
- Stages with no dependencies may omit it; `build_stages` falls back to `cls()`.
- **Direct constructors are unchanged** — every existing test that builds a stage by hand keeps working; `from_context` is additive sugar over `__init__`, never a replacement.

### 3. `build_stages` (core/pipeline.py)

The deps dict is deleted. Replacement:

```python
def build_stages(cfg, profile, seen, runner, publisher, force=False):
    ctx = StageContext(profile=profile, seen=seen, publisher=publisher,
                       runner=runner, models=cfg.models, force=force)
    stages = []
    for name in cfg.stages:
        cls = get_stage(name)
        stages.append(cls.from_context(ctx) if hasattr(cls, "from_context") else cls())
    return stages
```

A stage whose `from_context` needs a model entry that's missing from `cfg.models` fails there with today's KeyError semantics (fail-fast at build, named key in the message).

### 4. README

The "write your own stage" paragraph gains the last missing piece: implement `from_context` to receive dependencies — with the `DedupStage` three-liner as the example. This completes the claim that custom stages never touch core.

## Coordination (binding on ordering)

- **Multi-provider runners** (2026-07-02): both specs rewrite `build_stages`. **Land this spec first** — then the runners spec's chain resolution slots into `StageContext` (the `runner`+`models` fields become a `chains: dict[str, ModelChain]` field, and agent stages' `from_context` pulls `ctx.chains[name]`); its "Build wiring" section is amended by that plan, not this one. Reverse order works but does the same surgery twice.
- **Store backends** (2026-07-03): supplies the protocol types for `seen`/`publisher` fields. Either order; annotations tighten when both have landed.
- **Resume-match** (2026-07-03): its stage simply implements `from_context` (`cls(ctx.runner, ctx.models["resume_match"], ctx.profile)`) — one line in its plan, no spec change.

## Testing (no network, no tokens)

- Each built-in stage: `from_context(ctx)` produces an instance equivalent to direct construction (spot-check injected attrs).
- `build_stages`: uniform loop builds the full default stage list identically to today (e2e run unchanged); a registered toy stage with `from_context` receives the context; a toy stage without one and without deps constructs via `cls()`; missing model key fails at build naming the key.
- No existing test edits beyond what the function-signature change itself requires (`writer` param rename to `publisher` if taken — plan's choice; keeping `writer` is acceptable).

## Non-Goals

- No general DI container, no auto-wiring by inspection of `__init__` signatures (explicit `from_context` beats magic).
- No per-stage config blocks in yaml (stages read `ctx.models`/`ctx.profile`; richer per-stage config is a future need, not this one).
- No changes to the Stage runtime protocol (`run(job) -> Job` and `spec` are untouched).
