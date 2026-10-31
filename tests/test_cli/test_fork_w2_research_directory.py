"""Research scans must stay separate from the vault's internal files."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.core.vault import Vault


@pytest.mark.parametrize("research_dir", [".", "notes/..", "..", "../outside", "absolute", "symlink"])
def test_init_refuses_root_or_outside_research_dir(tmp_path, research_dir):
    root = tmp_path / "vault"
    if research_dir == "absolute":
        research_dir = str(tmp_path / "outside")
    elif research_dir == "symlink":
        root.mkdir()
        (root / "linked").symlink_to(tmp_path, target_is_directory=True)
        research_dir = "linked"
    result = CliRunner().invoke(app, ["init", str(root), "--dir", research_dir, "--json"])
    assert result.exit_code != 0
    assert json.loads(result.output)["ok"] is False
    assert not (root / ".hyperresearch").exists()
    assert not (tmp_path / "outside").exists()


def test_init_accepts_nested_research_directory(tmp_path):
    result = CliRunner().invoke(app, ["init", str(tmp_path / "vault"), "--dir", "docs/research", "--json"])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "vault" / "docs" / "research" / "notes").is_dir()


def test_legacy_root_research_scan_excludes_internal_files(tmp_path):
    vault = Vault.init(tmp_path / "legacy", research_dir=".")
    note = write_note(vault.notes_dir, "Real note")
    for folder in (".hyperresearch/exports", ".git", ".claude", ".codex", ".agents"):
        directory = vault.root / folder
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "internal.md").write_text("---\ntitle: Internal\n---\nNot a note.\n")
    plan = compute_sync_plan(vault)
    assert plan.to_add == [note]
    result = execute_sync(vault, plan)
    assert not result.errors
    assert result.added == 1
    again = execute_sync(vault, compute_sync_plan(vault, force=True))
    assert not again.errors
    assert vault.db.execute("SELECT COUNT(*) FROM notes").fetchone()[0] == 1
