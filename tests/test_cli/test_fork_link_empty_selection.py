"""`link --tag ""` is refused instead of linking the whole vault.

`elif tag:` read an empty --tag as no --tag, so with --auto every note in
the vault was linked and rewritten.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def vault_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root), "--name", "Empty Tag"]).exit_code == 0
    monkeypatch.chdir(root)
    for title, tag, body in [
        ("Attention Is All You Need", "ml", "The transformer paper."),
        ("Survey", "physics", "The paper Attention Is All You Need introduced transformers."),
    ]:
        result = runner.invoke(app, ["note", "new", title, "-t", tag, "-b", body, "--json"])
        assert result.exit_code == 0, result.output
    return root


@pytest.mark.parametrize("flags", [
    ["--tag", ""],
    ["--tag", "   "],
    ["--note", ""],
    ["--note", "survey", "--note", " "],
])
def test_empty_selection_is_refused(vault_root, flags):
    survey = vault_root / "research" / "notes" / "survey.md"
    before = survey.read_bytes()
    result = runner.invoke(app, ["link", "--auto", *flags, "--json"])
    assert result.exit_code == 1, result.output
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error_code"] == "NO_INPUT"
    assert survey.read_bytes() == before


def test_empty_tag_text_mode_names_the_option(vault_root):
    result = runner.invoke(app, ["link", "--auto", "--tag", ""])
    assert result.exit_code == 1, result.output
    assert "--tag" in result.output
    assert "Related" not in (vault_root / "research" / "notes" / "survey.md").read_text(encoding="utf-8")


def test_real_tag_still_links(vault_root):
    result = runner.invoke(app, ["link", "--auto", "--tag", "physics", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["links_added"] == {"survey": ["attention-is-all-you-need"]}
