import pytest

from job_pipeline.cli import main


def test_mock_cli_is_offline_and_preserves_real_files(tmp_path, monkeypatch, capsys):
    import httpx

    def no_network(*args, **kwargs):
        raise AssertionError("preview attempted network access")

    monkeypatch.setattr(httpx.Client, "request", no_network)
    monkeypatch.setattr(httpx, "get", no_network)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "existing.md").write_text("User-owned note")
    inbox = tmp_path / "inbox.txt"
    inbox.write_text("https://example.com/real-job\n")
    registry = tmp_path / "companies.json"
    registry.write_text('[{"name":"Real company","enabled":true}]')
    cfg = tmp_path / "pipeline.yaml"
    cfg.write_text(
        f"sources:\n  - {{type: manual, inbox: {inbox}}}\n"
        f"  - {{type: companies, file: {registry}}}\n"
        f"seeders: [{{type: existing_vault, path: {vault}}}]\n"
        "stages: [dedup, hard_filter, extract, dedup_fuzzy, skill_gap, score, publish]\n"
        "models: {extract: 'unavailable:model', skill_gap: haiku, score: opus}\n"
        f"output: {{vault: {vault}}}\n"
    )
    profile = tmp_path / "profile.md"
    profile.write_text("---\nblocklist: []\n---\nExample profile")
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert main(["run", "--config", str(cfg), "--profile", str(profile), "--mock"]) == 0
    output = capsys.readouterr().out
    assert "preview: published=1" in output
    assert "synthetic data, no saved changes" in output
    after = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    assert before == after


@pytest.mark.parametrize("flag", ["--force", "--reprocess"])
def test_mock_rejects_real_mutation_flags(flag):
    with pytest.raises(SystemExit) as exc:
        main(["run", "--mock", "--url", "https://example.com/job", flag])
    assert exc.value.code == 2
