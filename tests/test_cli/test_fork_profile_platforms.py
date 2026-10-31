"""`profile use` and `config agent-docs` refresh only the platforms a project has.

Both always did the Claude Code side and added Codex only when it was
installed, so on a Codex-only project `profile use` created .claude/ (a
PreToolUse hook, step skills, agents) and `config agent-docs` created
CLAUDE.md. They now follow `installed_platforms`, falling back to Claude Code
when neither is installed, as before.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


def _install(root, target):
    result = runner.invoke(app, ["install", str(root), "--target", target, "--json"])
    assert result.exit_code == 0, result.output


@pytest.fixture
def codex_only(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.chdir(root)
    _install(root, "codex")
    assert not (root / ".claude").exists()
    assert not (root / "CLAUDE.md").exists()
    return root


def test_profile_use_on_a_codex_only_project_adds_no_claude_files(codex_only):
    result = runner.invoke(app, ["profile", "use", "premier", "--json"])

    assert result.exit_code == 0, result.output
    assert not (codex_only / ".claude").exists()
    assert not (codex_only / "CLAUDE.md").exists()
    skill = codex_only / ".agents" / "skills" / "hyperresearch" / "SKILL.md"
    assert 'rendered from profile "premier"' in skill.read_text(encoding="utf-8")
    rerendered = json.loads(result.stdout)["data"]["rerendered"]
    assert rerendered and all(a.startswith("Codex:") for a in rerendered)


def test_config_agent_docs_on_a_codex_only_project_adds_no_claude_md(codex_only):
    result = runner.invoke(app, ["config", "agent-docs", "--json"])

    assert result.exit_code == 0, result.output
    assert not (codex_only / "CLAUDE.md").exists()
    assert json.loads(result.stdout)["data"]["modified"] == []


def test_config_agent_docs_text_names_the_file_it_checked(codex_only):
    result = runner.invoke(app, ["config", "agent-docs"])

    assert result.exit_code == 0, result.output
    assert "AGENTS.md" in result.output
    assert "CLAUDE.md" not in result.output


def test_both_platforms_are_still_refreshed_when_both_are_installed(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.chdir(root)
    _install(root, "all")

    result = runner.invoke(app, ["profile", "use", "premier", "--json"])

    assert result.exit_code == 0, result.output
    for skill in (
        root / ".claude" / "skills" / "hyperresearch" / "SKILL.md",
        root / ".agents" / "skills" / "hyperresearch" / "SKILL.md",
    ):
        assert 'rendered from profile "premier"' in skill.read_text(encoding="utf-8")


def test_a_vault_with_no_install_still_gets_claude_code(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)

    result = runner.invoke(app, ["profile", "use", "premier", "--json"])

    assert result.exit_code == 0, result.output
    assert (tmp_vault.root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").is_file()
