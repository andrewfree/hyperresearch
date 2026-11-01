"""Every Unicode spelling grouped into a stub must resolve on the first run."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note


@pytest.mark.parametrize("command", ["graph", "repair"])
def test_unicode_case_variants_resolve_together(tmp_vault, monkeypatch, command):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, "Source", body="[[ÉTUDE-Report Paper]] [[étude-report paper]]")
    args = ["graph", "stub", "-j"] if command == "graph" else [
        "repair", "--no-enrich", "--no-promote", "--no-index", "--no-docs", "-j"
    ]
    runner = CliRunner()

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    broken = runner.invoke(app, ["graph", "broken", "-j"])
    assert broken.exit_code == 0, broken.output
    assert json.loads(broken.output)["data"] == []
    files = sorted(tmp_vault.temp_dir.glob("*.md"))
    assert len(files) == 1
    for _ in range(2):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert sorted(tmp_vault.temp_dir.glob("*.md")) == files
