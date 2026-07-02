from job_pipeline.store.seen_index import SeenIndex


def test_mark_and_lookup(tmp_path):
    idx = SeenIndex(tmp_path / "seen.sqlite")
    assert not idx.has_url("abc")
    idx.mark("abc", "acme|engineer")
    assert idx.has_url("abc")
    assert idx.has_fuzzy("acme|engineer")
    assert not idx.has_fuzzy("other|role")


def test_persists_across_instances(tmp_path):
    db = tmp_path / "seen.sqlite"
    SeenIndex(db).mark("xyz")
    assert SeenIndex(db).has_url("xyz")


def test_mark_is_idempotent(tmp_path):
    idx = SeenIndex(tmp_path / "seen.sqlite")
    idx.mark("abc")
    idx.mark("abc")
    assert idx.count() == 1


def test_empty_fuzzy_key_never_matches(tmp_path):
    idx = SeenIndex(tmp_path / "seen.sqlite")
    idx.mark("abc", "")
    assert not idx.has_fuzzy("")
