"""Text output shows a broken link's target instead of '[]'.

graph broken, graph outlinks and lint printed `[[ref]]` through Rich, which
read `[ref]` as a style tag and dropped it, so the commands meant to list
broken links showed 'source line 1: []'. The same happened to the
'[embeddings]' in search --semantic's error.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def broken_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root), "--name", "Broken"]).exit_code == 0
    monkeypatch.chdir(root)
    result = runner.invoke(
        app, ["note", "new", "Source", "-b", "See [[missing-paper]] and [[Missing Paper Two]].", "--json"]
    )
    assert result.exit_code == 0, result.output
    return root


def _text(*args: str) -> str:
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result.output


def test_graph_broken_shows_targets(broken_vault):
    out = _text("graph", "broken")
    line = next(i for i, text in enumerate(
        (broken_vault / "research/notes/source.md").read_text().splitlines(), 1
    ) if "missing-paper" in text)
    assert f"source line {line}: [[missing-paper]]" in out
    assert f"source line {line}: [[Missing Paper Two]]" in out


def test_graph_outlinks_shows_broken_target(broken_vault):
    out = _text("graph", "outlinks", "source")
    assert "BROKEN [[missing-paper]] → missing-paper" in out


def test_lint_broken_links_shows_target(broken_vault):
    out = " ".join(_text("lint", "-r", "broken-links").split())  # undo Rich wrapping
    assert "Broken link: [[missing-paper]]" in out
    assert "Broken link: [[Missing Paper Two]]" in out


def test_search_semantic_error_keeps_the_config_section(broken_vault):
    result = runner.invoke(app, ["search", "paper", "--semantic"])
    assert result.exit_code == 1
    assert "set [embeddings] provider" in result.output
