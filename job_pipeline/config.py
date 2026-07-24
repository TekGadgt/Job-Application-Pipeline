"""Fail-fast config loading: profile.md (YAML frontmatter + prose) and pipeline.yaml."""
from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator


class Profile(BaseModel):
    score_floor: int | None = None
    blocklist: list[str] = []
    body: str = ""                      # prose: resume + fuzzy preferences


class OutputConfig(BaseModel):
    vault: Path


class Limits(BaseModel):
    max_agent_jobs_per_run: int = Field(default=40, gt=0)


CANONICAL_IMPORT_KEYS = frozenset({
    "company", "position", "location", "type_of_work", "source_url",
    "date_found", "date_of_contact", "employer_address", "employer_phone",
    "employer_email", "employer_contact_person", "result_of_contact",
    "application_status", "score",
})


class ImportConfig(BaseModel):
    path: Path
    fields: dict[str, str] = {}
    keep_unmapped: bool = True

    @field_validator("fields")
    @classmethod
    def _only_canonical_keys(cls, v: dict[str, str]) -> dict[str, str]:
        unknown = sorted(set(v) - CANONICAL_IMPORT_KEYS)
        if unknown:
            raise ValueError(f"unknown canonical import field(s): {', '.join(unknown)}")
        return v


class PipelineConfig(BaseModel):
    sources: list[dict] = []
    seeders: list[dict] = []
    stages: list[str]
    models: dict[str, str] = {}
    output: OutputConfig
    limits: Limits = Limits()
    import_: ImportConfig | None = Field(default=None, alias="import")

    # A yaml key whose entries are all commented out parses as None, not empty.
    @field_validator("sources", "seeders", mode="before")
    @classmethod
    def _none_as_empty_list(cls, v: object) -> object:
        return [] if v is None else v

    @field_validator("models", mode="before")
    @classmethod
    def _none_as_empty_dict(cls, v: object) -> object:
        return {} if v is None else v


FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)


def load_profile(path: Path | str) -> Profile:
    text = Path(path).read_text()
    m = FRONTMATTER_RE.match(text)
    if not m:
        raise ValueError(
            f"{path}: profile must start with a closed YAML frontmatter block (--- ... ---)"
        )
    data = yaml.safe_load(m.group(1)) or {}
    return Profile(**data, body=m.group(2).strip())


def load_pipeline_config(path: Path | str) -> PipelineConfig:
    data = yaml.safe_load(Path(path).read_text()) or {}
    return PipelineConfig(**data)
