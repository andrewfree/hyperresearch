"""lint rejects an unknown --rule name and no longer offers a no-op --fix.

`rules_to_run = [rule]` was never checked against the rule table, so a typo
such as `-r broken-link` ran no rule at all and reported 'Vault is healthy'
with exit 0, hiding the warnings `-r broken-links` reports.

`--fix` ('Auto-fix what's possible') was declared but never read, so it
changed nothing while the help promised fixes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def lint_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root), "--name", "Lint"]).exit_code == 0
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["note", "new", "Source", "-b", "See [[missing-paper]].", "--json"])
    assert result.exit_code == 0, result.output
    return root


def test_known_rule_still_runs(lint_vault):
    result = runner.invoke(app, ["lint", "-r", "broken-links", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["summary"]["warnings"] == 1


def test_unknown_rule_is_an_error(lint_vault):
    result = runner.invoke(app, ["lint", "-r", "broken-link"])
    assert result.exit_code == 1, result.output
    assert "healthy" not in result.output
    assert "Unknown lint rule 'broken-link'" in result.output
    assert "broken-links" in result.output  # the valid names are listed


def test_unknown_rule_json_error_envelope(lint_vault):
    result = runner.invoke(app, ["lint", "-r", "broken-link", "--json"])
    assert result.exit_code == 1, result.output
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error_code"] == "UNKNOWN_RULE"
    assert "broken-links" in data["error"]


def test_help_does_not_offer_fix(lint_vault):
    result = runner.invoke(app, ["lint", "--help"])
    assert result.exit_code == 0, result.output
    assert "--fix" not in result.output
    assert "Auto-fix" not in result.output


def test_fix_is_rejected_rather_than_ignored(lint_vault):
    notes = sorted((lint_vault / "research").rglob("*.md"))
    before = [p.read_bytes() for p in notes]
    result = runner.invoke(app, ["lint", "--fix"])
    assert result.exit_code == 2  # usage error: no such option
    assert "No such option" in result.output
    assert [p.read_bytes() for p in notes] == before
