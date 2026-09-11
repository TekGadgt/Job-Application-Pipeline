"""Wires config -> stages/sources/seeders and runs one batch."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from job_pipeline.config import PipelineConfig, Profile
from job_pipeline.core.job import Job
from job_pipeline.core.orchestrator import DeterministicOrchestrator
from job_pipeline.core.registry import get_runner, get_seeder, get_source, get_stage
from job_pipeline.core.runner import AgentRunner, LazyRunner, ModelChain, ModelChainEntry
from job_pipeline.sources.base import HintedSource
from job_pipeline.store.obsidian import ObsidianWriter
from job_pipeline.store.seen_index import SeenIndex

# side-effect imports: populate the registries
import job_pipeline.stages.rules      # noqa: F401
import job_pipeline.stages.agents     # noqa: F401
import job_pipeline.stages.publish    # noqa: F401
import job_pipeline.sources.manual    # noqa: F401
import job_pipeline.sources.feeds     # noqa: F401
import job_pipeline.sources.companies  # noqa: F401
import job_pipeline.seeders.existing_vault  # noqa: F401
import job_pipeline.runners  # noqa: F401

log = logging.getLogger("job_pipeline")


@dataclass
class RunSummary:
    published: int = 0
    rejected: int = 0
    errored: int = 0
    deferred: int = 0
    notes: list[Path] = field(default_factory=list)


def build_stages(cfg: PipelineConfig, profile: Profile, seen: SeenIndex,
                 runner_override: AgentRunner | None, writer: ObsidianWriter,
                 force: bool = False,
                 provider_instances: dict[str, AgentRunner] | None = None):
    instances = provider_instances if provider_instances is not None else {}

    def chain_for(stage: str) -> ModelChain:
        entries: list[ModelChainEntry] = []
        for ref in cfg.models[stage]:
            if runner_override is not None:
                runner = runner_override
            else:
                provider = "anthropic" if ref.provider == "claude" else ref.provider
                runner = instances.get(provider)
                if runner is None:
                    kwargs = cfg.runners.get(ref.provider, {})
                    if ref.provider == "claude" and not kwargs:
                        kwargs = cfg.runners.get("anthropic", {})
                    runner = LazyRunner(partial(get_runner(provider), **kwargs))
                    instances[provider] = runner
            entries.append(ModelChainEntry(ref.provider, runner, ref.model))
        return ModelChain(entries)

    deps = {
        "dedup": lambda c: c(seen),
        "hard_filter": lambda c: c(profile),
        "dedup_fuzzy": lambda c: c(seen),
        "score_floor": lambda c: c(profile),
        "extract": lambda c: c(chain_for("extract")),
        "skill_gap": lambda c: c(chain_for("skill_gap"), profile),
        "score": lambda c: c(chain_for("score"), profile),
        "publish": lambda c: c(writer, force),
    }
    stages = []
    for name in cfg.stages:
        cls = get_stage(name)
        stages.append(deps[name](cls) if name in deps else cls())
    return stages


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


def run_pipeline(cfg: PipelineConfig, profile: Profile,
                 runner_override: AgentRunner | None = None,
                 sources=None, extra_urls: list[str] | None = None,
                 force: bool = False, db_path: Path | None = None) -> RunSummary:
    db = db_path or cfg.output.vault.expanduser() / ".job_pipeline.seen.sqlite"
    seen = SeenIndex(db)
    writer = ObsidianWriter(cfg.output.vault)

    for spec in cfg.seeders:
        spec = dict(spec)
        kind = spec.pop("type")
        n = get_seeder(kind)(**spec).seed(seen)
        log.info("seeder %s marked %d jobs", kind, n)

    if sources is None:
        sources = build_sources(cfg, extra_urls)

    jobs: list[Job] = []
    origin: dict[str, object] = {}
    for src in sources:
        try:
            fetched = src.fetch()
        except Exception as exc:  # noqa: BLE001 — one dead feed doesn't kill the run
            log.warning("source %s failed: %s", type(src).__name__, exc)
            continue
        for j in fetched:
            origin[j.id] = src
            jobs.append(j)

    registry_file = next(
        (s.get("file") for s in cfg.sources if s.get("type") == "companies"), None)
    if registry_file:
        manual_urls = [j.url for j in jobs if j.source == "manual"]
        if manual_urls:
            from job_pipeline.sources.companies import harvest_urls
            try:
                harvest_urls(registry_file, manual_urls)
            except Exception as exc:  # noqa: BLE001 — never crash the run over data
                log.warning("url harvesting into %s failed: %s", registry_file, exc)

    provider_instances: dict[str, AgentRunner] = {}
    try:
        stages = build_stages(
            cfg, profile, seen, runner_override, writer, force, provider_instances,
        )
        result = DeterministicOrchestrator(cfg.limits.max_agent_jobs_per_run).run(jobs, stages)
    finally:
        if runner_override is None:
            for runner in {id(value): value for value in provider_instances.values()}.values():
                close = getattr(runner, "close", None)
                if close is not None:
                    try:
                        close()
                    except Exception as exc:  # cleanup must not discard terminal outcomes
                        log.warning("provider cleanup failed: %s", exc)

    summary = RunSummary(deferred=len(result.deferred))
    for job in result.processed:
        if job.errored:
            summary.errored += 1
            continue                      # stays unseen -> retries next run
        if job.rejected:
            summary.rejected += 1
        else:
            summary.published += 1
            summary.notes.append(writer.path_for(job))
        seen.mark(job.id, job.fuzzy_key)  # terminal only
        src = origin.get(job.id)
        if src is not None:
            src.on_terminal(job)
    if summary.deferred:
        log.warning("%d jobs deferred by agent cap; they retry next run", summary.deferred)
    return summary
