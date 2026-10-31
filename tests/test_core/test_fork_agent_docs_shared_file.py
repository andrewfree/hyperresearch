"""CLAUDE.md and AGENTS.md as one file (a symlink) carry both runtimes' instructions.

Both blurbs use the same marked section, so with CLAUDE.md symlinked to
AGENTS.md, `install --target all` wrote the Claude blurb and then replaced it
with the Codex one: Claude Code read Codex-only instructions, and every run
reported both files updated because the section flipped back and forth. When
the two names are one file, its section now holds the blurb of every runtime
installed there, so both read their own and a second run changes nothing.
"""

from __future__ import annotations

import json
import os

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.agent_docs import (
    HYPERRESEARCH_SECTION_MARKER,
    inject_agent_docs,
)

runner = CliRunner()

CLAUDE_LINE = "Run a research session with `/hyperresearch <query>`."
CODEX_LINE = "Run a research session with `$hyperresearch <query>`."

needs_symlinks = pytest.mark.skipif(
    os.name == "nt", reason="creating symlinks needs privileges on Windows"
)


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


def _shared(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENTS.md").write_text("# Shared rules\n\nKeep this.\n", encoding="utf-8")
    (root / "CLAUDE.md").symlink_to("AGENTS.md")
    return root / "AGENTS.md"


@needs_symlinks
def test_install_all_with_a_symlinked_claude_md_keeps_both_blurbs(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    shared = _shared(root)
    monkeypatch.chdir(root)

    first = runner.invoke(app, ["install", str(root), "--target", "all", "--json"])
    assert first.exit_code == 0, first.output

    text = shared.read_text(encoding="utf-8")
    assert text.startswith("# Shared rules\n\nKeep this.\n")
    assert text.count(HYPERRESEARCH_SECTION_MARKER) == 1
    assert CLAUDE_LINE in text
    assert CODEX_LINE in text
    assert (root / "CLAUDE.md").is_symlink()

    second = runner.invoke(app, ["install", str(root), "--target", "all", "--json"])
    assert second.exit_code == 0, second.output
    assert json.loads(second.stdout)["data"]["agent_docs"] == []
    assert shared.read_text(encoding="utf-8") == text

    again = runner.invoke(app, ["config", "agent-docs", "--json"])
    assert json.loads(again.stdout)["data"]["modified"] == []


@needs_symlinks
def test_a_symlinked_claude_md_on_a_claude_only_install_gets_only_the_claude_blurb(tmp_path):
    root = tmp_path / "proj"
    shared = _shared(root)

    assert inject_agent_docs(root, platform="claude") == ["CLAUDE.md (appended)"]

    text = shared.read_text(encoding="utf-8")
    assert CLAUDE_LINE in text
    assert CODEX_LINE not in text
    assert inject_agent_docs(root, platform="claude") == []


def test_separate_files_keep_one_blurb_each(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root), "--target", "all", "--json"])
    assert result.exit_code == 0, result.output

    claude = (root / "CLAUDE.md").read_text(encoding="utf-8")
    codex = (root / "AGENTS.md").read_text(encoding="utf-8")
    assert CLAUDE_LINE in claude and CODEX_LINE not in claude
    assert CODEX_LINE in codex and CLAUDE_LINE not in codex
