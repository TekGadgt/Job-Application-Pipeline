"""job-pipeline run — the on-demand (and cron-able) entrypoint."""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

from job_pipeline.config import load_pipeline_config, load_profile
from job_pipeline.core.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job-pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run the pipeline once")
    run.add_argument("--config", type=Path, default=Path("config/pipeline.yaml"))
    run.add_argument("--profile", type=Path, default=Path("config/profile.md"))
    run.add_argument("--url", action="append", default=[], help="feed a job URL (repeatable)")
    run.add_argument("--force", action="store_true", help="overwrite user-edited notes")
    run.add_argument("--mock", action="store_true", help="dry run with a mock agent")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_pipeline_config(args.config)      # fail fast, before any tokens
    profile = load_profile(args.profile)

    if args.mock:
        from job_pipeline.core.runner import MockRunner
        runner = MockRunner([])   # agent stages will error-isolate per job
    else:
        from job_pipeline.core.sdk_runner import SDKRunner
        runner = SDKRunner()

    s = run_pipeline(cfg, profile, runner, extra_urls=args.url, force=args.force)
    print(f"published={s.published} rejected={s.rejected} "
          f"errored={s.errored} deferred={s.deferred}")
    for note in s.notes:
        print(f"  -> {note}")
    return 0
