"""`search --include-body` prints each note's body in text mode.

The flag fetched the bodies into the results, but the text renderer printed
only id, title, status and snippet, so the output was identical with and
without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()

FILLER = " ".join(f"filler{i}" for i in range(80))
BODY = f"linked line one. {FILLER} Unique tail sentence with [bold]literal[/bold] brackets."


@pytest.fixture
def body_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root), "--name", "Body"]).exit_code == 0
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["note", "new", "Target", "-b", BODY, "--json"])
    assert result.exit_code == 0, result.output
    return root


def test_include_body_prints_the_body(body_vault):
    result = runner.invoke(app, ["search", "linked", "--include-body"])
    assert result.exit_code == 0, result.output
    assert "Unique tail sentence with [bold]literal[/bold] brackets." in result.output


def test_without_include_body_the_body_is_not_printed(body_vault):
    result = runner.invoke(app, ["search", "linked"])
    assert result.exit_code == 0, result.output
    assert "target" in result.output
    assert "Unique tail sentence" not in result.output
