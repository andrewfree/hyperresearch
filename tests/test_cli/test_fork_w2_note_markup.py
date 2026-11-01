"""Note text is literal data at Rich output boundaries."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()
TITLE = "Weekly thread on [/r/MachineLearning]"
BODY = "Code: x[red]y and [bold]hi[/bold] [/unknown]"


@pytest.fixture
def markup_note(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["note", "new", TITLE, "-b", BODY, "-t", "[bold]tag[/bold]", "-j"])
    assert result.exit_code == 0, result.output
    return tmp_vault, json.loads(result.output)["data"]["id"]


@pytest.mark.parametrize("command", ["list", "show", "multi", "meta", "search"])
def test_note_data_prints_literally(markup_note, command):
    _, note_id = markup_note
    args = {
        "list": ["note", "list"],
        "show": ["note", "show", note_id],
        "multi": ["note", "show", note_id, note_id],
        "meta": ["note", "show", note_id, "--meta"],
        "search": ["search", "MachineLearning"],
    }[command]
    result = runner.invoke(app, args, env={"COLUMNS": "240"})
    assert result.exit_code == 0, repr(result.exception)
    assert TITLE in result.output
    assert "[bold]tag[/bold]" in result.output


def test_raw_note_matches_file(markup_note):
    vault, note_id = markup_note
    row = vault.db.execute("SELECT path FROM notes WHERE id = ?", (note_id,)).fetchone()
    result = runner.invoke(app, ["note", "show", note_id, "--raw"])
    assert result.exit_code == 0, repr(result.exception)
    assert result.output == (vault.root / row["path"]).read_text(encoding="utf-8")


def test_search_snippet_prints_literally(markup_note):
    result = runner.invoke(app, ["search", "Code"], env={"COLUMNS": "240"})
    assert result.exit_code == 0, repr(result.exception)
    assert "x[red]y" in result.output
    assert "[bold]hi[/bold]" in result.output
