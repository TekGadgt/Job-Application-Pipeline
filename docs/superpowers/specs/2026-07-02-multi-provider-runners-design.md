# Multi-Provider Runners & Model Fallback Chains — Design Spec

**Date:** 2026-07-02
**Status:** Implemented on review branch; pending merge and live-provider verification (2026-09-11)
**Depends on:** Stage Package Refactor spec (2026-07-02) — land that first; this spec's stage edits assume the `stages/agents/` package layout.

## Goal

Let each agent stage run against an ordered fallback chain of `provider:model` pairs, configured in `pipeline.yaml`, so that:

1. Forks can add a new provider (raw API, local models) by writing one adapter class and registering it — no core edits.
2. A stage survives a provider outage or usage-limit wall by falling through to the next chain entry (e.g. `claude:opus` → hypothetical `codex:gpt-5`).

The implementation ships `anthropic` (`claude` alias), `openai`, and `mock`.
The live providers use local Claude Code and ChatGPT/Codex authentication.
OpenCode Go was removed after subscription cancellation on 2026-09-11.

## Config Syntax (binding)

`models` values become a chain — a list of `provider:model` strings, tried in order:

```yaml
models:
  extract:   [openai:gpt-5.6-luna, anthropic:haiku]
  skill_gap: [openai:gpt-5.6-luna, anthropic:sonnet]
  score:     [openai:gpt-5.6-terra, anthropic:opus]
runners:
  openai: {max_attempts: 3}
  anthropic: {max_attempts: 3}
```

**Backward compatibility:** the current shorthand must keep working. Normalization rules, applied by a pydantic validator at config load:

- A bare string is a one-element chain: `extract: haiku` ≡ `extract: [haiku]`.
- An entry without a `:` gets the default provider: `haiku` ≡ `anthropic:haiku`.
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

- Resolve provider names while building stages; unknown names fail before execution.
- Instantiate each provider **lazily and once per run**, on its first actual use.
  Missing CLI/authentication raises `RunnerError`, allowing fallback; startup
  failures are cached for the rest of the run. Other exception types propagate.
  `claude` and `anthropic` share one instance. Only started providers are closed.
- `run_pipeline`'s `runner: AgentRunner` parameter becomes `runner_override: AgentRunner | None = None`. When set (tests, `--mock`), every chain entry uses it regardless of provider — this keeps `--mock` and the e2e tests trivial. When `None`, providers come from the registry.

### 7. Provider layout: the `runners/` package (binding)

Providers get the same predictable one-module-per-adapter layout as stages/sources/seeders:

```
job_pipeline/runners/
  __init__.py     # imports every provider module (registration side-effect), __all__
  anthropic.py    # Claude Agent SDK; registers "anthropic" and compatibility alias "claude"
  openai.py       # local Codex SDK with ChatGPT subscription-auth guard
  mock.py         # registers MockRunner as "mock" (class itself stays in core/runner.py —
                  #   it is a test double first; this module is just the registration)
```

`core/sdk_runner.py` is removed. The `ANTHROPIC_API_KEY` billing guard moves with
the Anthropic adapter; OpenAI refuses API-key authentication. A fork adds another provider by copying the
closest adapter, registering its name, importing it from `runners/__init__.py`, and
referencing it in a model chain.

### 8. CLI

`--mock` runs an offline preview using synthetic listings and schema-specific
replies. Sources and seeders are skipped; output and seen-index use a temporary
directory and are discarded. Real inbox and registry files remain untouched.
`--url` only supplies preview identifiers. `--force` and `--reprocess` are rejected
in preview mode. Any errored jobs produce a nonzero CLI exit status.

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

- No async runners and no providers beyond the two subscription-backed adapters.
- No per-entry timeout/budget knobs.
- No orchestrator awareness of chains (it still sees stages; the AI-orchestrator seam is untouched).
- No changes to `max_agent_jobs_per_run` accounting (a job entering agent stages counts once, regardless of fallbacks).
