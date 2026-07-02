"""API-friendly pull sources: RSS, Greenhouse boards, Lever postings."""
from __future__ import annotations

from datetime import datetime, UTC

import feedparser

from job_pipeline.core.job import Job
from job_pipeline.core.registry import register_source
from job_pipeline.sources.base import http_get_json, http_get_text


@register_source("rss")
class RssSource:
    def __init__(self, url: str) -> None:
        self.url = url
        self._get = http_get_text

    def fetch(self) -> list[Job]:
        feed = feedparser.parse(self._get(self.url))
        return [
            Job(source="rss", url=e.link,
                raw_text=f"{e.get('title', '')}\n{e.get('summary', '')}",
                fetched_at=datetime.now(UTC))
            for e in feed.entries
        ]

    def on_terminal(self, job: Job) -> None: ...


@register_source("greenhouse")
class GreenhouseSource:
    def __init__(self, board: str) -> None:
        self.board = board
        self._get = http_get_json

    def fetch(self) -> list[Job]:
        data = self._get(
            f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs?content=true"
        )
        jobs = []
        for item in data.get("jobs", []):
            j = Job(source="greenhouse", url=item["absolute_url"],
                    raw_text=f"{item.get('title', '')}\n{item.get('content', '')}",
                    fetched_at=datetime.now(UTC))
            j.title = item.get("title", "")
            j.location = (item.get("location") or {}).get("name", "")
            jobs.append(j)
        return jobs

    def on_terminal(self, job: Job) -> None: ...


@register_source("lever")
class LeverSource:
    def __init__(self, org: str) -> None:
        self.org = org
        self._get = http_get_json

    def fetch(self) -> list[Job]:
        data = self._get(f"https://api.lever.co/v0/postings/{self.org}?mode=json")
        jobs = []
        for item in data:
            j = Job(source="lever", url=item["hostedUrl"],
                    raw_text=f"{item.get('text', '')}\n{item.get('descriptionPlain', '')}",
                    fetched_at=datetime.now(UTC))
            j.title = item.get("text", "")
            j.location = (item.get("categories") or {}).get("location", "")
            jobs.append(j)
        return jobs

    def on_terminal(self, job: Job) -> None: ...
