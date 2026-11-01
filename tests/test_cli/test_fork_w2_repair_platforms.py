"""Repair refreshes docs for the installed runtimes."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.vault import Vault


@pytest.mark.parametrize("platforms", [("codex",), ("claude",), ("claude", "codex"), ()])
def test_repair_uses_installed_platforms(tmp_path, monkeypatch, platforms):
    vault = Vault.init(tmp_path / "vault", name="Docs", platforms=())
    from hyperresearch.core.hooks import install_hooks

    for platform in platforms:
        install_hooks(vault.root, platform=platform)
    monkeypatch.chdir(vault.root)
    for name in ("CLAUDE.md", "AGENTS.md"):
        (vault.root / name).unlink(missing_ok=True)
    result = CliRunner().invoke(app, [
        "repair", "--no-stub", "--no-enrich", "--no-promote", "--no-index", "--json",
    ])
    assert result.exit_code == 0, result.output
    expected = platforms or ("claude",)
    assert (vault.root / "CLAUDE.md").exists() == ("claude" in expected)
    assert (vault.root / "AGENTS.md").exists() == ("codex" in expected)
    docs = json.loads(result.output)["data"]["agent_docs"]
    assert len(docs) == len(expected)
