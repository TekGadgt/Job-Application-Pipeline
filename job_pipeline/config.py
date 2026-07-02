"""Fail-fast config loading: profile.md (YAML frontmatter + prose) and pipeline.yaml."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class LocationRules(BaseModel):
    remote: bool = False
    allowed_metros: list[str] = []


class Profile(BaseModel):
    salary_floor: int | None = None
    locations: LocationRules = LocationRules()
    blocklist: list[str] = []
    must_have_skills: list[str] = []
    nice_to_have: list[str] = []
    salary_not_listed: Literal["keep", "reject"] = "keep"
    body: str = ""                      # prose: resume + fuzzy preferences


class OutputConfig(BaseModel):
    vault: Path
    keep_rejects: bool = True


class Limits(BaseModel):
    max_agent_jobs_per_run: int = Field(default=40, gt=0)


class PipelineConfig(BaseModel):
    sources: list[dict] = []
    seeders: list[dict] = []
    stages: list[str]
    models: dict[str, str] = {}
    output: OutputConfig
    limits: Limits = Limits()


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
