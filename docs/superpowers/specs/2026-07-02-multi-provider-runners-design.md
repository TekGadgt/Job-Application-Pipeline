# Multi-Provider Runners & Model Fallback Chains — Design Spec

**Date:** 2026-07-02
**Status:** Approved for planning
**Depends on:** Stage Package Refactor spec (2026-07-02) — land that first; this spec's stage edits assume the `stages/agents/` package layout.

## Goal

Let each agent stage run against an ordered fallback chain of `provider:model` pairs, configured in `pipeline.yaml`, so that:

1. Forks can add a new provider (Codex, OpenCode, raw API, local models) by writing one adapter class and registering it — no core edits.
2. A stage survives a provider outage or usage-limit wall by falling through to the next chain entry (e.g. `claude:opus` → hypothetical `codex:gpt-5`).

We ship exactly two providers: `claude` (the existing SDKRunner) and `mock` (tests/`--mock`). Third-party adapters are documentation, not code (YAGNI — and keeps the default install subscription-only with zero extra credentials).

## Config Syntax (binding)

`models` values become a chain — a list of `provider:model` strings, tried in order:

```yaml
models:
  extract:   [claude:haiku]
  skill_gap: [claude:sonnet]
  score:     [claude:opus, claude:sonnet]     # fall back to sonnet if opus fails
runners:                                      # optional per-provider constructor kwargs
  claude: {max_attempts: 3}
```

**Backward compatibility:** the current shorthand must keep working. Normalization rules, applied by a pydantic validator at config load:

- A bare string is a one-element chain: `extract: haiku` ≡ `extract: [haiku]`.
- An entry without a `:` gets the default provider: `haiku` ≡ `claude:haiku`.
- The existing example file (`models: {extract: haiku, skill_gap: sonnet, score: opus}`) parses identically to today's behavior.

Malformed entries (`:model`, `provider:`, empty list, empty string) fail at load with a message naming the stage key — fail-fast like the rest of `config.py`.

## Components

### 1. `ModelRef` (config.py)

Frozen pydantic model: `provider: str`, `model: str`, classmethod `parse("provider:model") -> ModelRef` implementing the defaulting rules above. `PipelineConfig.models` becomes `dict[str, list[ModelRef]]` with a `field_validator(mode="before")` doing the normalization. `PipelineConfig.runners: dict[str, dict] = {}` added.

### 2. Runner registry (core/registry.py)

Fourth `_make_pair` table: `register_runner, get_runner = _make_pair(_RUNNERS, "runner")`. This is the fork seam — an adapter module does:

```python
@register_runner("codex")
class CodexRunner:
    def run(self, prompt: str, model: str, schema: type[T]) -> T: ...
```

### 3. `AgentRunner` protocol — unchanged

`run(prompt, model, schema) -> T` stays exactly as-is (`core/runner.py:17-18`). It is the *provider adapter* contract. Adapters must raise `RunnerError` for anything that should trigger fallback (exhausted retries, invalid replies, provider/transport failures — wrap unexpected exceptions). A raise of anything other than `RunnerError` is treated as a bug and propagates (caught by the orchestrator's per-job isolation, marking the job errored — same as today).

### 4. `ModelChain` (core/runner.py) — the new seam stages see

```python
class ModelChain:
    def __init__(self, entries: list[tuple[AgentRunner, str]]) -> None: ...
    def run(self, prompt: str, schema: type[T]) -> T: ...
```

Semantics:
- Try entries in order. On `RunnerError`, log a warning naming the failed `provider:model` and the reason, then try the next.
- All entries exhausted → raise `RunnerError` listing every entry's failure. The orchestrator's existing per-job try/except marks the job errored; it retries next run (unchanged terminal semantics).
- No cross-entry retry budget: each adapter owns its own retries (SDKRunner already loops `max_attempts`).

### 5. Stage signature change (stages/agents/*)

Agent stages currently take `(runner: AgentRunner, model: str)`. They change to take a single `chain: ModelChain` and call `self.chain.run(prompt, Schema)`. The stage no longer knows model names at all — provider+model is config, bound at build time. This is a deliberate interface break inside our own package; tests wrap their MockRunner:

```python
ModelChain([(MockRunner([...]), "haiku")])
```

### 6. Build wiring (core/pipeline.py)

`build_stages` gains a runner-resolution step:

- Instantiate each provider **lazily and once per run**: only providers referenced by some stage's chain get constructed, with kwargs from `cfg.runners.get(provider, {})`.
- `run_pipeline`'s `runner: AgentRunner` parameter becomes `runner_override: AgentRunner | None = None`. When set (tests, `--mock`), every chain entry uses it regardless of provider — this keeps `--mock` and the e2e tests trivial. When `None`, providers come from the registry.

### 7. SDKRunner registration

`@register_runner("claude")` on the existing class. The `ANTHROPIC_API_KEY` billing guard stays exactly as-is — it protects the `claude` provider only; other providers own their own credential handling. `MockRunner` registers as `"mock"` (usable directly in yaml chains, e.g. for dry-run configs).

### 8. CLI

`--mock` behavior unchanged from the user's view: passes `runner_override=MockRunner([])`.

## What `cost_tier` becomes

Unchanged in this spec (metadata only), but the README note gets one sentence: `cost_tier` describes the stage's *intent*; the actual spend is whatever the configured chain does. Deriving/validating tier-vs-chain is explicitly out of scope.

## Documentation Deliverable

README gains a "Bring your own provider" section: the `AgentRunner` contract (raise `RunnerError` to trigger fallback), the registry decorator, the `runners:` kwargs map, and a ~15-line sketch of a subprocess-based adapter (illustrative, not shipped or tested against a real CLI).

## Testing

- Config: string/list/`provider:model` normalization; malformed entries raise with the stage key in the message; legacy example yaml parses to `[claude:x]` chains.
- ModelChain: first-success short-circuits; RunnerError falls through in order; exhaustion raises with all failures; non-RunnerError propagates.
- Stages: existing agent-stage tests updated to wrap MockRunner in a one-entry chain — assertions otherwise unchanged.
- Wiring: build_stages constructs one runner instance per provider (identity-checked across stages); unknown provider in yaml raises the registry's KeyError at build, not mid-run; `runner_override` bypasses the registry.
- e2e: one fallback e2e — score chain `[failing-runner, MockRunner]` publishes via the second entry. (Failing runner = MockRunner exhausted, which raises RunnerError.)
- No network, no tokens: the live SDK integration test stays as-is under the `integration` marker.

## Non-Goals

- No shipped non-Claude adapter, no new dependencies, no async runners.
- No per-entry timeout/budget knobs.
- No orchestrator awareness of chains (it still sees stages; the AI-orchestrator seam is untouched).
- No changes to `max_agent_jobs_per_run` accounting (a job entering agent stages counts once, regardless of fallbacks).
