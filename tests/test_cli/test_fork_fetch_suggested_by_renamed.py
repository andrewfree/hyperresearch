"""fetch --suggested-by on an already-fetched URL finds the note by its id.

The breadcrumb was appended to the file found by rglob(f"{note_id}.md"),
so a note whose id no longer matches its filename (an id edit, supported
since #159) was not found, nothing was written, and the command still said
"breadcrumb(s) already present". Offline: a fake provider serves the page.
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

URL = "https://site.example.org/article"
TEXT = "River sediments settle in estuaries over long periods of time. " * 20


class _Provider:
    name = "fake"

    def fetch(self, url: str) -> WebResult:
        return WebResult(url=url, title="River Sediments", content=TEXT)


@pytest.fixture
def renamed(tmp_path: Path, monkeypatch) -> Path:
    """A fetched note whose frontmatter id was edited: river-sediments.md, id river-renamed."""
    assert runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Breadcrumbs"]).exit_code == 0
    root = tmp_path / "kb"
    os.chdir(root)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _Provider())
    assert runner.invoke(app, ["fetch", URL, "--json"]).exit_code == 0
    path = root / "research" / "notes" / "river-sediments.md"
    text = path.read_text(encoding="utf-8")
    assert "id: river-sediments\n" in text
    path.write_text(text.replace("id: river-sediments\n", "id: river-renamed\n"), encoding="utf-8")
    assert runner.invoke(app, ["sync", "--json"]).exit_code == 0
    return path


def _suggest(*sources: str) -> dict:
    args = ["fetch", URL, "--suggested-by-reason", "why", "--json"]
    for src in sources:
        args += ["--suggested-by", src]
    return json.loads(runner.invoke(app, args).stdout)


def test_the_breadcrumb_lands_in_the_note_whose_id_was_edited(renamed: Path):
    data = _suggest("src-note")["data"]
    assert data["note_id"] == "river-renamed"
    assert data["backlinks_added"] == 1
    assert "*Suggested by [[src-note]] — why*" in renamed.read_text(encoding="utf-8")

    again = _suggest("src-note")["data"]
    assert again["backlinks_added"] == 0
    assert again["message"] == "URL already fetched; breadcrumb(s) already present"


def test_a_missing_note_file_is_an_error_not_already_present(renamed: Path, monkeypatch):
    from hyperresearch.core.vault import Vault

    # The notes row outlives its file only until the next sync, so keep
    # fetch's auto-sync from dropping it.
    monkeypatch.setattr(Vault, "auto_sync", lambda self: None)
    renamed.unlink()

    envelope = _suggest("src-note")
    assert envelope["ok"] is False
    assert envelope["error_code"] == "NOTE_NOT_FOUND"
    assert "river-renamed" in envelope["error"]
