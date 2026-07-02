import hashlib
from job_pipeline.store.seen_index import SeenIndex
from job_pipeline.seeders.existing_vault import ExistingVaultSeeder

NOTE = """---
company: "Acme Corp"
position: "Senior Engineer"
source_url: "https://x.com/jobs/1"
---
body
"""


def url_hash(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def test_seed_marks_url_and_fuzzy_key(tmp_path):
    (tmp_path / "note.md").write_text(NOTE)
    (tmp_path / "not-a-job.md").write_text("no frontmatter")
    idx = SeenIndex(tmp_path / "seen.sqlite")
    count = ExistingVaultSeeder(path=tmp_path).seed(idx)
    assert count == 1
    assert idx.has_url(url_hash("https://x.com/jobs/1"))
    assert idx.has_fuzzy("acmecorp|seniorengineer")


def test_custom_field_mapping(tmp_path):
    (tmp_path / "n.md").write_text('---\nlink: "https://y.com/2"\n---\nx')
    idx = SeenIndex(tmp_path / "seen.sqlite")
    assert ExistingVaultSeeder(path=tmp_path, url_field="link").seed(idx) == 1
    assert idx.has_url(url_hash("https://y.com/2"))
