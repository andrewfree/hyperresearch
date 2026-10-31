"""Graph and note status output preserve literal vault text."""

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note

runner = CliRunner()
TITLE = "Regex [/a-z] and [red]classes[/red]"


@pytest.fixture
def graph_vault(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, TITLE, note_id="regex", body="See [[target]].")
    write_note(tmp_vault.notes_dir, "Target", note_id="target", body="See [[regex]].")
    write_note(tmp_vault.notes_dir, TITLE + " orphan", note_id="orphan")
    tmp_vault.auto_sync()
    return tmp_vault


@pytest.mark.parametrize("args", [
    ["graph", "backlinks", "target"], ["graph", "outlinks", "target"],
    ["graph", "orphans"], ["graph", "hubs"], ["graph", "rank"],
])
def test_graph_titles_are_literal(graph_vault, args):
    result = runner.invoke(app, args, env={"COLUMNS": "240"})
    assert result.exit_code == 0, repr(result.exception)
    assert TITLE in result.output


@pytest.mark.parametrize("args", [
    ["note", "show", "[/unknown]"], ["note", "edit", "[/unknown]"],
    ["note", "update", "[/unknown]", "--status", "draft"],
    ["note", "rm", "[/unknown]", "--force"],
    ["graph", "backlinks", "[/unknown]"], ["graph", "outlinks", "[/unknown]"],
])
def test_missing_ids_are_literal(graph_vault, args):
    result = runner.invoke(app, args)
    assert result.exit_code in (0, 1)
    assert "[/unknown]" in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_note_move_path_is_literal(graph_vault):
    result = runner.invoke(app, ["note", "mv", "regex", "research/notes/[red]new.md"])
    assert result.exit_code == 0, repr(result.exception)
    assert "[red]new.md" in result.output
