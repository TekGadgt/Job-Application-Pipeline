"""job-pipeline import — adopt an existing tracker folder into the vault.

Zero tokens, no stages, never overwrites. Distinct from the existing_vault
seeder: the seeder makes the pipeline IGNORE old jobs; import ADOPTS them.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from job_pipeline.config import PipelineConfig
from job_pipeline.stages.rules import legacy_fuzzy_key, make_fuzzy_key
from job_pipeline.store.obsidian import _slug
from job_pipeline.store.seen_index import SeenIndex


@dataclass
class ImportSummary:
    imported: int = 0
    skipped_existing: int = 0
    skipped_unparseable: int = 0
    seen_marked: int = 0
    planned: list[tuple[Path, Path]] = field(default_factory=list)


def _new_frontmatter(mapped: dict, job_id: str, fuzzy: str) -> dict:
    position = str(mapped.get("position", ""))
    fm = {
        "company": mapped.get("company", ""),
        "position": position,
        "location": mapped.get("location", ""),
        "employer_address": mapped.get("employer_address", ""),
        "employer_phone": mapped.get("employer_phone", ""),
        "employer_email": mapped.get("employer_email", ""),
        "employer_contact_person": mapped.get("employer_contact_person", ""),
        "date_found": mapped.get("date_found", ""),
        "date_of_contact": mapped.get("date_of_contact", ""),
        "source_url": mapped.get("source_url", ""),
        "type_of_work": mapped.get("type_of_work", position),
        "result_of_contact": mapped.get("result_of_contact", "found"),
        "application_status": mapped.get("application_status", "Unsubmitted"),
        "score": mapped.get("score"),
        "comp_min": None,
        "comp_max": None,
        "comp_currency": None,
        "comp_period": None,
        "status": "imported",   # never to_review: permanently protected by skip-on-edit
        "job_id": job_id,
        "role_key": fuzzy or None,
        "possible_duplicate": False,
    }
    return fm


def run_import(cfg: PipelineConfig, dry_run: bool = False) -> ImportSummary:
    imp = cfg.import_
    if imp is None:
        raise ValueError("config has no `import:` block — nothing to import")
    vault = cfg.output.vault.expanduser()
    root = imp.path.expanduser()
    summary = ImportSummary()
    seen = None if dry_run else SeenIndex(vault / ".job_pipeline.seen.sqlite")
    if not dry_run:
        vault.mkdir(parents=True, exist_ok=True)
    for note in sorted(root.rglob("*.md")):
        text = note.read_text()
        if not text.startswith("---"):
            summary.skipped_unparseable += 1
            continue
        try:
            _, fm_text, body = text.split("---", 2)
            old = yaml.safe_load(fm_text) or {}
        except (ValueError, yaml.YAMLError):
            summary.skipped_unparseable += 1
            continue
        if not isinstance(old, dict):
            summary.skipped_unparseable += 1
            continue
        mapped = {canon: old[key] for canon, key in imp.fields.items() if key in old}
        url = str(mapped.get("source_url") or "")
        if url:
            job_id = hashlib.sha256(url.encode()).hexdigest()[:16]
        else:
            job_id = hashlib.sha256(
                note.relative_to(root).as_posix().encode()).hexdigest()[:16]
        company = str(mapped.get("company", ""))
        title = str(mapped.get("position", ""))
        loc = str(mapped.get("location", ""))
        if legacy_fuzzy_key(company, title) == "|":
            fuzzy = ""
        elif loc:
            fuzzy = make_fuzzy_key(company, title, loc)
        else:
            fuzzy = legacy_fuzzy_key(company, title)   # block-everywhere semantics
        target = vault / f"{_slug(company)}-{_slug(title)}-{job_id[:8]}.md"
        if target.exists():
            summary.skipped_existing += 1
            # heal the seen-index anyway: a prior run may have been interrupted
            # between writing the note and marking, or the db replaced/lost
            if seen is not None and (url or fuzzy):
                seen.mark(job_id, fuzzy)
                summary.seen_marked += 1
            continue
        if dry_run:
            summary.imported += 1
            summary.planned.append((note, target))
            continue
        new_fm = _new_frontmatter(mapped, job_id, fuzzy)
        if imp.keep_unmapped:
            consumed = set(imp.fields.values())
            for key, value in old.items():
                if key not in consumed and key not in new_fm:
                    new_fm[key] = value
        if not body.startswith(("\n", "\r")):
            body = "\n" + body   # keep the closing fence on its own line
        target.write_text(
            "---\n" + yaml.safe_dump(new_fm, sort_keys=False) + "---" + body
        )
        summary.imported += 1
        if url or fuzzy:
            seen.mark(job_id, fuzzy)
            summary.seen_marked += 1
    if seen is not None:
        seen.close()
    return summary
