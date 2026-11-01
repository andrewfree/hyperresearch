"""Initialization cannot put notes in directories excluded from sync."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app


@pytest.mark.parametrize("research_dir", [
    ".hyperresearch", ".hyperresearch/library", ".git", ".claude/research",
    ".codex", ".agents", "linked",
])
def test_init_rejects_internal_research_directory(tmp_path, research_dir):
    root = tmp_path / "vault"
    if research_dir == "linked":
        root.mkdir()
        (root / "linked").symlink_to(root / ".hyperresearch", target_is_directory=True)
    result = CliRunner().invoke(app, ["init", str(root), "--dir", research_dir, "--json"])
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_RESEARCH_DIR"
    assert not (root / ".hyperresearch").exists()
