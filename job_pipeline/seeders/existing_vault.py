"""Opt-in seeder: pre-populate the seen-index from an existing Obsidian job vault."""
from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from job_pipeline.core.registry import register_seeder
from job_pipeline.stages.rules import make_fuzzy_key
from job_pipeline.store.seen_index import SeenIndex


@register_seeder("existing_vault")
class ExistingVaultSeeder:
    def __init__(self, path: Path | str, url_field: str = "source_url",
                 company_field: str = "company", title_field: str = "position") -> None:
        self.path = Path(path).expanduser()
        self.url_field = url_field
        self.company_field = company_field
        self.title_field = title_field

    def seed(self, seen_index: SeenIndex) -> int:
        count = 0
        for note in self.path.glob("*.md"):
            text = note.read_text()
            if not text.startswith("---"):
                continue
            try:
                _, fm, _ = text.split("---", 2)
                data = yaml.safe_load(fm) or {}
            except (ValueError, yaml.YAMLError):
                continue
            url = data.get(self.url_field)
            if not url:
                continue
            url_hash = hashlib.sha256(str(url).encode()).hexdigest()[:16]
            fuzzy = make_fuzzy_key(
                str(data.get(self.company_field, "")), str(data.get(self.title_field, ""))
            )
            seen_index.mark(url_hash, fuzzy if fuzzy != "|" else "")
            count += 1
        return count
