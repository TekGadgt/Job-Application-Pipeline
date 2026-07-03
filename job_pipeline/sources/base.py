from __future__ import annotations

from typing import Protocol

import httpx

from job_pipeline.core.job import Job


class Source(Protocol):
    def fetch(self) -> list[Job]: ...
    def on_terminal(self, job: Job) -> None: ...


def http_get_text(url: str) -> str:
    resp = httpx.get(url, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def http_get_json(url: str):
    resp = httpx.get(url, timeout=20, follow_redirects=True)
    resp.raise_for_status()
    return resp.json()


class HintedSource:
    """Wraps a source, stamping a per-source extract hint onto every fetched job.

    Existing source classes stay ignorant of hints; the wrapper satisfies the
    same Source protocol and delegates on_terminal so inbox-consumption
    semantics are unchanged.
    """

    def __init__(self, inner: Source, hint: str) -> None:
        self.inner = inner
        self.hint = hint

    def fetch(self) -> list[Job]:
        jobs = self.inner.fetch()
        for job in jobs:
            job.extract_hint = self.hint
        return jobs

    def on_terminal(self, job: Job) -> None:
        self.inner.on_terminal(job)
