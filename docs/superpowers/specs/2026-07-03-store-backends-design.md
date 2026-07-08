# Store Backends — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Motivation:** Stages, sources, seeders, and (specced) runners are all registry-pluggable with a predictable one-module-per-adapter layout. The two stores are not: `run_pipeline` concretely instantiates `SeenIndex` (sqlite) and `ObsidianWriter` (`core/pipeline.py:78-79`) — no protocol, no registry, no `type:` in config. Publisher pluggability is the most fork-valuable seam in the repo ("I don't use Obsidian"); the state-store seam is cheap insurance and gives the future server/UI a clean read surface.

## Goal

Two new registry kinds with the house layout, each shipping exactly one backend:

- **State store** (`sqlite`) — the seen index today; the observability spec's run history joins the same backend when it lands.
- **Publisher** (`obsidian`) — note output.

Default configs are byte-compatible: absent `type:` keys mean today's behavior exactly.

## Config Syntax (binding)

```yaml
state:  {type: sqlite}                       # optional block; optional path override
output: {type: obsidian, vault: ~/vault/jobs}
```

- `state:` absent → `{type: sqlite}` with the current default path (`<vault>/.job_pipeline.seen.sqlite`). `state: {type: sqlite, path: /elsewhere.db}` overrides the location (subsumes the CLI-invisible `db_path` parameter as user-facing config).
- `output.type` defaults to `obsidian`; existing configs parse unchanged. Backend-specific keys (like `vault`) pass through to the backend constructor, mirroring how source specs work.

## Layout & Registries (binding)

```
job_pipeline/store/
  __init__.py        # imports every backend module (registration side-effect), __all__
  base.py            # StateStore + Publisher protocols
  sqlite_state.py    # SeenIndex moves here verbatim, @register_state_store("sqlite")
  obsidian.py        # ObsidianWriter stays, gains @register_publisher("obsidian")
```

Registries: two more `_make_pair` tables in `core/registry.py` (`register_state_store`/`get_state_store`, `register_publisher`/`get_publisher`). `store/seen_index.py` is removed — no shim (clean-break policy from the source module split); consumers update imports: `core/pipeline.py`, `stages/rules/dedup.py`, `stages/rules/dedup_fuzzy.py`, `seeders/existing_vault.py`, and the affected test files' import lines (import-line edits only).

## Protocols (base.py)

```python
class StateStore(Protocol):
    def has_url(self, url_hash: str) -> bool: ...
    def has_fuzzy(self, fuzzy_key: str) -> bool: ...
    def mark(self, url_hash: str, fuzzy_key: str = "") -> None: ...
    def count(self) -> int: ...
    def close(self) -> None: ...

class Publisher(Protocol):
    def path_for(self, job: Job) -> Path: ...
    def is_user_touched(self, job: Job) -> bool: ...
    def write(self, job: Job) -> Path: ...
```

Type annotations in stages/seeders switch from the concrete classes to the protocols (runtime-irrelevant, documents the contract). `Publisher.path_for`/`write` returning `Path` is honest for file-based backends; a future non-file backend (Notion, webhook) returns an identifier-ish `Path`-compatible value or motivates a widening then — not now (YAGNI).

## Wiring (core/pipeline.py)

`run_pipeline` resolves both via registry: `get_state_store(state.type)(**state_kwargs)`, `get_publisher(output.type)(**output_kwargs)`. The existing `db_path` parameter stays as a test seam and overrides `state.path` when given.

## Coordination

- **Reprocess flag** (2026-07-03): `unmark(url_hash) -> bool` joins the `StateStore` protocol when it lands (either order works; whichever is second adds one line).
- **Observability** (2026-07-03): `RunHistory` lives in `store/sqlite_state.py`'s backend module (same db file, same backend family) — its spec needs no amendment; the run-history *protocol* surface can stay concrete until a second state backend actually exists.
- **Vault-import / resume-match / comp-in-notes / application-status** (2026-07-03): all write through `ObsidianWriter` — unaffected; import's writer usage goes through the registry-resolved publisher automatically.
- **Local server/UI** (2026-07-03): reads state via the store classes, not raw sqlite — satisfied by this layout naturally.
- **Source module split** (2026-07-03): establishes the clean-break/no-shim and `__init__` aggregator conventions this spec reuses; land the split first (conventions land once).

## Testing (no network, no tokens)

- Registry: both kinds resolvable by name; unknown `type:` in config fails at build with the registry's known-names KeyError.
- Config: absent `state:` → sqlite at the vault-derived default; `state.path` override honored; `output.type` default `obsidian`; existing example yaml parses to identical behavior.
- Protocol conformance: `SeenIndex` and `ObsidianWriter` pass `isinstance` checks against the (runtime-checkable) protocols.
- Existing seen-index/obsidian/e2e tests pass with import-line edits only.

## Non-Goals

- No second backend of either kind (no postgres, no Notion, no CSV — the seam is the deliverable; backends are fork territory, README says so).
- No async store APIs, no connection pooling, no migrations framework.
- No splitting `obsidian.py` further (writer + VEC frontmatter is one cohesive responsibility).
