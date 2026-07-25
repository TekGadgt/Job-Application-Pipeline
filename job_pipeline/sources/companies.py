"""Meta-source: expand the companies.json registry into per-ATS sources."""
from __future__ import annotations

import logging
from pathlib import Path

from job_pipeline.ats_patterns import detect
from job_pipeline.config import CompanyEntry, load_companies, save_companies
from job_pipeline.core.job import Job
from job_pipeline.core.registry import get_source, register_source

log = logging.getLogger("job_pipeline")

BANNED = {"workable"}   # aggressive IP bans — see docs/JobBoardDetection.md


# Single source of truth for maker functions; SUPPORTED is derived so the two
# structures can't drift apart (E3 extends _MAKERS: ashby, smartrecruiters, ...).
_MAKERS = {
    "greenhouse": lambda slug: get_source("greenhouse")(board=slug),
    "lever": lambda slug: get_source("lever")(org=slug),
}
SUPPORTED = set(_MAKERS)


def _default_make(ats: str, slug: str):
    return _MAKERS[ats](slug)


def harvest_urls(registry_path: Path | str, urls: list[str]) -> int:
    """Append registry entries for manual URLs matching known ATS patterns."""
    entries = load_companies(registry_path)
    known = {(e.ats_platform, e.slug) for e in entries}
    added = 0
    for url in urls:
        hit = detect(url)
        if not hit or hit in known:
            continue
        ats, slug = hit
        if ats in BANNED:
            continue
        entries.append(CompanyEntry(name=slug, ats_platform=ats, slug=slug,
                                    source="url_harvest", enabled=True))
        known.add(hit)
        added += 1
        log.info("harvested %s as %s source (from %s)", slug, ats, url)
    if added:
        save_companies(registry_path, entries)
    return added


@register_source("companies")
class CompaniesSource:
    def __init__(self, file: Path | str, make=None) -> None:
        self.file = Path(file).expanduser()
        self.make = make or _default_make

    def fetch(self) -> list[Job]:
        entries = load_companies(self.file)
        jobs: list[Job] = []
        unsupported = 0
        dirty = False
        fetched_pairs: set[tuple[str, str]] = set()
        for entry in entries:
            if not entry.enabled:
                continue
            if entry.slug is None and entry.careers_url:
                hit = detect(entry.careers_url)
                if hit and hit[0] in BANNED:
                    # Don't mutate or persist a banned-platform resolution
                    # (FINDING 6b): refuse before touching the entry so a
                    # later save() triggered by some *other* dirty entry in
                    # this run can never carry this resolution to disk.
                    log.warning("refusing %s (%s): banned platform", entry.name, hit[0])
                    continue
                if hit:
                    entry.ats_platform, entry.slug = hit
                    dirty = True
            if entry.ats_platform in BANNED:
                log.warning("refusing %s (%s): banned platform", entry.name, entry.ats_platform)
                continue
            if entry.ats_platform not in SUPPORTED or not entry.slug:
                unsupported += 1
                continue
            pair = (entry.ats_platform, entry.slug)
            if pair in fetched_pairs:
                log.info("companies: skipping %s, duplicate (%s/%s) already fetched this run",
                          entry.name, entry.ats_platform, entry.slug)
                continue
            fetched_pairs.add(pair)
            try:
                fetched = self.make(entry.ats_platform, entry.slug).fetch()
            except Exception as exc:  # noqa: BLE001 — one dead board doesn't kill the run
                log.warning("companies: %s (%s/%s) failed: %s",
                            entry.name, entry.ats_platform, entry.slug, exc)
                continue
            for j in fetched:
                j.company = entry.name
                j.company_context = entry.notes or ""
            jobs.extend(fetched)
        if dirty:
            save_companies(self.file, entries)
        if unsupported:
            log.info("companies: %d entries await unsupported-platform mappers (E3/E4)", unsupported)
        return jobs

    def on_terminal(self, job: Job) -> None:
        pass
