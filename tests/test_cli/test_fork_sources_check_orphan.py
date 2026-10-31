"""`sources check` agrees with `fetch` about a URL whose note was deleted.

Deleting a note leaves its sources row with note_id NULL (ON DELETE SET
NULL). `fetch` treats that URL as new, but `sources check` tested only that
a row existed, so it answered {"exists": true, "note_id": null} and
"note 'None'", and the researcher agent, which fetches only "if not already
fetched", skipped the source. Offline: a fake provider serves the page.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult

runner = CliRunner()

URL = "https://site.example.org/q?[/docs]"
TEXT = "River sediments settle in estuaries over long periods of time. " * 20


class _Provider:
    name = "fake"

    def fetch(self, url: str) -> WebResult:
        return WebResult(url=url, title="River Sediments", content=TEXT)


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Orphans"]).exit_code == 0
    root = tmp_path / "kb"
    os.chdir(root)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _Provider())
    fetched = runner.invoke(app, ["fetch", URL, "--json"])
    assert fetched.exit_code == 0, fetched.output
    return root


def _check(*extra: str):
    return runner.invoke(app, ["sources", "check", URL, *extra], env={"COLUMNS": "200"})


def test_a_live_source_is_reported_as_fetched(vault_dir: Path):
    data = json.loads(_check("--json").stdout)["data"]
    assert data["exists"] is True
    assert data["note_id"] == "river-sediments"

    human = _check()
    assert human.exit_code == 0, human.output
    assert f"Found: {URL} → note 'river-sediments'" in human.output


def test_a_source_whose_note_was_deleted_is_not_fetched(vault_dir: Path):
    removed = runner.invoke(app, ["note", "rm", "river-sediments", "--json"])
    assert removed.exit_code == 0, removed.output

    data = json.loads(_check("--json").stdout)["data"]
    assert data["exists"] is False
    assert data["orphaned"] is True
    assert data["url"] == URL

    human = _check()
    assert human.exit_code == 0, human.output
    assert "None" not in human.output
    assert f"Not fetched: {URL}" in human.output

    listed = runner.invoke(app, ["sources", "list"], env={"COLUMNS": "200"})
    assert listed.exit_code == 0, listed.output
    assert f"orphaned {URL} → (deleted)" in listed.output

    # And fetch agrees: the URL is new again.
    again = runner.invoke(app, ["fetch", URL, "--json"])
    assert again.exit_code == 0, again.output


def test_an_unknown_url_is_not_fetched_and_not_orphaned(vault_dir: Path):
    result = runner.invoke(app, ["sources", "check", "https://other.example.org/", "--json"])
    data = json.loads(result.stdout)["data"]
    assert data == {"exists": False, "url": "https://other.example.org/"}
