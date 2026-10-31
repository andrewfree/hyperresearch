"""Vault discovery failures follow the CLI's JSON error contract."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()
COMMANDS = [
    ["graph", "backlinks", "missing"], ["graph", "outlinks", "missing"],
    ["graph", "orphans"], ["graph", "broken"], ["graph", "stub"],
    ["graph", "hubs"], ["graph", "rank"], ["lint"], ["tags"],
    ["index", "build"], ["index", "list"], ["index", "show", "missing"],
    ["export", "vault", "exported"], ["export", "json"],
]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("json_mode", [True, False])
def test_no_vault_is_a_clean_error(tmp_path, monkeypatch, command, json_mode):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, command + (["--json"] if json_mode else []))
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    if json_mode:
        data = json.loads(result.stdout)
        assert data["ok"] is False
        assert data["error_code"] == "NO_VAULT"
    else:
        assert "No hyperresearch vault found" in result.output


def test_missing_index_page_returns_json(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["index", "show", "nope", "-j"])
    assert result.exit_code == 1
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error_code"] == "NOT_FOUND"
    assert "nope.md" in data["error"]
