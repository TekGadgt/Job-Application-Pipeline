"""job-pipeline run — the on-demand (and cron-able) entrypoint."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from job_pipeline.config import load_pipeline_config, load_profile
from job_pipeline.core.pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="job-pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run the pipeline once")
    run.add_argument("--config", type=Path, default=Path("config/pipeline.yaml"))
    run.add_argument("--profile", type=Path, default=Path("config/profile.md"))
    run.add_argument("--url", action="append", default=[],
                     help="process only this URL (repeatable; configured sources are skipped)")
    run.add_argument("--reprocess", action="store_true",
                     help="clear the seen-index entry for each --url before running")
    run.add_argument("--force", action="store_true", help="overwrite user-edited notes")
    run.add_argument("--mock", action="store_true", help="dry run with a mock agent")

    imp = sub.add_parser("import", help="convert an existing tracker folder into pipeline notes")
    imp.add_argument("--config", type=Path, default=Path("config/pipeline.yaml"))
    imp.add_argument("--dry-run", action="store_true",
                     help="print the per-note plan without writing anything")
    args = parser.parse_args(argv)

    if args.cmd == "import":
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
        cfg = load_pipeline_config(args.config)
        if cfg.import_ is None:
            print("error: config has no `import:` block — see README "
                  "'Importing an existing tracker'", file=sys.stderr)
            return 2
        from job_pipeline.store.vault_import import run_import
        s = run_import(cfg, dry_run=args.dry_run)
        if args.dry_run:
            for old, new in s.planned:
                print(f"  {old} -> {new}")
        print(f"imported={s.imported} skipped_existing={s.skipped_existing} "
              f"skipped_unparseable={s.skipped_unparseable} seen_marked={s.seen_marked}")
        return 0

    if args.reprocess and not args.url:
        parser.error("--reprocess requires --url (no blanket un-marking)")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    cfg = load_pipeline_config(args.config)      # fail fast, before any tokens

    if args.reprocess:
        import hashlib
        from job_pipeline.store.seen_index import SeenIndex
        seen = SeenIndex(cfg.output.vault.expanduser() / ".job_pipeline.seen.sqlite")
        for url in args.url:
            was = seen.unmark(hashlib.sha256(url.encode()).hexdigest()[:16])
            logging.info("reprocessing %s (%s)", url, "was seen" if was else "was not seen")
        seen.close()
    profile = load_profile(args.profile)

    if args.mock:
        from job_pipeline.core.runner import MockRunner
        runner = MockRunner([])   # agent stages will error-isolate per job
    else:
        from job_pipeline.core.sdk_runner import SDKRunner
        runner = SDKRunner()

    # --url means "process exactly these": skip configured sources (and the inbox)
    sources = None
    if args.url:
        from job_pipeline.sources.manual import ManualSource
        sources = [ManualSource(urls=args.url)]

    s = run_pipeline(cfg, profile, runner, sources=sources, force=args.force)
    print(f"published={s.published} rejected={s.rejected} "
          f"errored={s.errored} deferred={s.deferred}")
    for note in s.notes:
        print(f"  -> {note}")
    return 0
