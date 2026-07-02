"""User-fed URLs: repeatable --url flags plus a plaintext inbox file (a queue)."""
from __future__ import annotations

from datetime import datetime, UTC
from pathlib import Path

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_source
from job_pipeline.sources.base import http_get_text


@register_source("manual")
class ManualSource:
    def __init__(self, inbox: Path | str | None = None, urls: list[str] | None = None) -> None:
        self.inbox = Path(inbox).expanduser() if inbox else None
        self.urls = urls or []
        self._get = http_get_text
        self._inbox_urls: set[str] = set()

    def _read_inbox(self) -> list[str]:
        if not self.inbox or not self.inbox.exists():
            return []
        return [ln.strip() for ln in self.inbox.read_text().splitlines() if ln.strip()]

    def fetch(self) -> list[Job]:
        inbox_urls = self._read_inbox()
        self._inbox_urls = set(inbox_urls)
        jobs = []
        for url in [*inbox_urls, *self.urls]:
            job = Job(source="manual", url=url, raw_text="", fetched_at=datetime.now(UTC))
            try:
                job.raw_text = self._get(url)
            except Exception as exc:  # noqa: BLE001 — a dead URL degrades one job
                job.mark_errored("manual_fetch", str(exc))
            jobs.append(job)
        return jobs

    def on_terminal(self, job: Job) -> None:
        """Remove the job's line from the inbox once it is published or rejected."""
        if not self.inbox or job.url not in self._inbox_urls:
            return
        lines = [ln for ln in self._read_inbox() if ln != job.url]
        self.inbox.write_text("".join(f"{ln}\n" for ln in lines))
