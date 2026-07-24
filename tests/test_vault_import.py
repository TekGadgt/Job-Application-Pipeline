from pathlib import Path
import hashlib
import yaml
from job_pipeline.config import PipelineConfig, OutputConfig, ImportConfig
from job_pipeline.store.seen_index import SeenIndex
from job_pipeline.store.vault_import import run_import

OLD_NOTE = """---
position: Software Engineer
company: OldCo
status: In Talks
date-applied: 2025-11-02
website: https://oldco.example/careers/123
has-referral: true
---
## Notes
Talked to recruiter on 11/2.
"""

FIELDS = {
    "company": "company",
    "position": "position",
    "application_status": "status",
    "date_of_contact": "date-applied",
    "source_url": "website",
}


def make_cfg(tmp_path, **import_kw):
    old = tmp_path / "old"
    old.mkdir(exist_ok=True)
    kw = dict(path=old, fields=FIELDS, keep_unmapped=True)
    kw.update(import_kw)
    return PipelineConfig(
        stages=["dedup"], output=OutputConfig(vault=tmp_path / "vault"),
        **{"import": ImportConfig(**kw)},
    ), old


def read_note(vault):
    notes = list(Path(vault).glob("*.md"))
    assert len(notes) == 1
    text = notes[0].read_text()
    _, fm, body = text.split("---", 2)
    return notes[0], yaml.safe_load(fm), body


def test_import_maps_fields_and_preserves_body(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    s = run_import(cfg)
    assert s.imported == 1
    path, fm, body = read_note(tmp_path / "vault")
    assert fm["company"] == "OldCo"
    assert fm["position"] == "Software Engineer"
    assert fm["application_status"] == "In Talks"
    assert str(fm["date_of_contact"]) == "2025-11-02"
    assert fm["source_url"] == "https://oldco.example/careers/123"
    assert fm["status"] == "imported"          # never to_review
    assert fm["has-referral"] is True           # keep_unmapped carried through
    assert body == "\n## Notes\nTalked to recruiter on 11/2.\n"  # byte-exact
    assert path.name.startswith("oldco-software-engineer-")


def test_import_drop_unmapped_when_disabled(tmp_path):
    cfg, old = make_cfg(tmp_path, keep_unmapped=False)
    (old / "oldco.md").write_text(OLD_NOTE)
    run_import(cfg)
    _, fm, _ = read_note(tmp_path / "vault")
    assert "has-referral" not in fm


def test_import_is_idempotent(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    assert run_import(cfg).imported == 1
    s2 = run_import(cfg)
    assert s2.imported == 0 and s2.skipped_existing == 1


def test_import_marks_seen_url_and_fuzzy(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    s = run_import(cfg)
    assert s.seen_marked == 1
    idx = SeenIndex(tmp_path / "vault" / ".job_pipeline.seen.sqlite")
    h = hashlib.sha256(b"https://oldco.example/careers/123").hexdigest()[:16]
    assert idx.has_url(h)
    assert idx.has_fuzzy("oldco|softwareengineer")   # legacy 2-part: no location mapped


def test_import_urlless_note_keys_by_relative_path(tmp_path):
    cfg, old = make_cfg(tmp_path)
    note = OLD_NOTE.replace("website: https://oldco.example/careers/123\n", "")
    (old / "oldco.md").write_text(note)
    assert run_import(cfg).imported == 1
    _, fm, _ = read_note(tmp_path / "vault")
    assert fm["job_id"] == hashlib.sha256(b"oldco.md").hexdigest()[:16]
    assert run_import(cfg).imported == 0    # stable id across runs


def test_import_skips_unparseable(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "not-a-note.md").write_text("just some text, no frontmatter")
    s = run_import(cfg)
    assert s.imported == 0 and s.skipped_unparseable == 1


def test_import_skips_non_dict_frontmatter(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "weird.md").write_text("---\n- a\n- b\n---\nbody\n")
    s = run_import(cfg)
    assert s.imported == 0 and s.skipped_unparseable == 1


def test_dry_run_writes_nothing(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    s = run_import(cfg, dry_run=True)
    assert s.imported == 1 and len(s.planned) == 1
    assert not list((tmp_path / "vault").glob("*.md"))
    # pure existence check: instantiating SeenIndex would itself create the dir/db
    assert not (tmp_path / "vault" / ".job_pipeline.seen.sqlite").exists()


def test_dry_run_does_not_create_vault_dir(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    run_import(cfg, dry_run=True)
    assert not (tmp_path / "vault").exists()


def test_import_body_without_leading_newline_stays_well_formed(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "sloppy.md").write_text("---\nposition: Engineer\ncompany: OldCo\n---body glued to fence\n")
    s = run_import(cfg)
    assert s.imported == 1
    _, fm, body = read_note(tmp_path / "vault")
    assert fm["company"] == "OldCo"          # frontmatter re-parses as a dict
    assert body == "\nbody glued to fence\n"


def test_rerun_heals_missing_seen_index_for_existing_note(tmp_path):
    cfg, old = make_cfg(tmp_path)
    (old / "oldco.md").write_text(OLD_NOTE)
    run_import(cfg)
    db = tmp_path / "vault" / ".job_pipeline.seen.sqlite"
    db.unlink()                                    # simulate interrupted run / lost db
    s = run_import(cfg)
    assert s.imported == 0 and s.skipped_existing == 1
    assert s.seen_marked == 1                      # healed, not silently skipped
    h = hashlib.sha256(b"https://oldco.example/careers/123").hexdigest()[:16]
    assert SeenIndex(db).has_url(h)


def test_run_import_without_block_raises_clear_error(tmp_path):
    import pytest
    cfg = PipelineConfig(stages=["dedup"], output=OutputConfig(vault=tmp_path / "vault"))
    with pytest.raises(ValueError, match="import"):
        run_import(cfg)


def test_urlless_id_uses_posix_relative_path(tmp_path):
    cfg, old = make_cfg(tmp_path)
    sub = old / "2025"
    sub.mkdir()
    note = OLD_NOTE.replace("website: https://oldco.example/careers/123\n", "")
    (sub / "oldco.md").write_text(note)
    run_import(cfg)
    _, fm, _ = read_note(tmp_path / "vault")
    assert fm["job_id"] == hashlib.sha256(b"2025/oldco.md").hexdigest()[:16]
