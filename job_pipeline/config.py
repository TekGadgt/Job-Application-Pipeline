"""Fail-fast config loading: profile.md (YAML frontmatter + prose) and pipeline.yaml."""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

log = logging.getLogger("job_pipeline")


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


class CompanyEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    website: str | None = None
    careers_url: str | None = None
    ats_platform: str | None = None
    slug: str | None = None
    domain: str | None = None
    company_size: str | None = None
    stage: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    notes: str | None = None
    source: str | None = None
    enabled: bool = True


def load_companies(path: Path | str) -> list[CompanyEntry]:
    """Tolerant registry load: bad entries warn+skip, missing file warns+[]."""
    path = Path(path).expanduser()
    if not path.exists():
        log.warning("companies registry %s not found; no companies loaded", path)
        return []
    try:
        raw_list = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("companies registry %s is invalid/unreadable: %s", path, exc)
        return []
    if not isinstance(raw_list, list):
        log.warning("companies registry %s: top level must be a list; ignoring", path)
        return []
    entries: list[CompanyEntry] = []
    for i, raw in enumerate(raw_list):
        try:
            entries.append(CompanyEntry(**raw))
        except Exception as exc:  # noqa: BLE001 — data file, never crash the run
            log.warning("companies registry: skipping entry %d: %s", i, exc)
    return entries


def save_companies(path: Path | str, entries: list[CompanyEntry]) -> None:
    """Rewrite the registry, carrying forward entries the loader could not parse.

    load_companies() silently drops entries that fail validation; if we then
    write out only the successfully-parsed entries, that loss becomes
    permanent. Re-read the file here and preserve any unparsable entries
    verbatim so a load -> save round trip never destroys data.
    """
    path = Path(path).expanduser()
    unparsed: list[dict] = []
    if path.exists():
        try:
            raw_list = json.loads(path.read_text())
            if isinstance(raw_list, list):
                for raw in raw_list:
                    if not isinstance(raw, dict):
                        log.warning("companies registry %s: dropping non-object entry %r", path, raw)
                        continue
                    try:
                        CompanyEntry(**raw)
                    except Exception:  # noqa: BLE001 — unparseable: preserve verbatim
                        unparsed.append(raw)
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass   # unreadable file: nothing to preserve
    payload = [e.model_dump(exclude_none=False) for e in entries] + unparsed
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, path)
