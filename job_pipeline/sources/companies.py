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


def _default_make(ats: str, slug: str):
    if ats == "greenhouse":
        return get_source("greenhouse")(board=slug)
    if ats == "lever":
        return get_source("lever")(org=slug)
    raise KeyError(ats)


SUPPORTED = {"greenhouse", "lever"}   # E3 extends: ashby, smartrecruiters, ...


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
        for entry in entries:
            if not entry.enabled:
                continue
            if entry.slug is None and entry.careers_url:
                hit = detect(entry.careers_url)
                if hit:
                    entry.ats_platform, entry.slug = hit
                    dirty = True
            if entry.ats_platform in BANNED:
                log.warning("refusing %s (%s): banned platform", entry.name, entry.ats_platform)
                continue
            if entry.ats_platform not in SUPPORTED or not entry.slug:
                unsupported += 1
                continue
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
