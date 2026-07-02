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
