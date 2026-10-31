"""Tags round-trip without treating their punctuation as separators."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note

runner = CliRunner()


@pytest.fixture
def tagged_vault(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, "Comma tag", tags=["ml,ai", ",", 'x"y'], parent="ml")
    write_note(tmp_vault.notes_dir, "No tags")
    tmp_vault.auto_sync()
    return tmp_vault


@pytest.mark.parametrize("command", ["show", "list", "topic", "search"])
def test_cli_tags_round_trip(tagged_vault, command):
    args = {
        "show": ["note", "show", "comma-tag"],
        "list": ["note", "list", "--tag", "ml,ai"],
        "topic": ["topic", "show", "ml"],
        "search": ["search", "Comma"],
    }[command]
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)["data"]
    note = {"show": lambda: data, "topic": lambda: data["notes"][0],
            "search": lambda: data["results"][0], "list": lambda: data[0]}[command]()
    assert sorted(note["tags"]) == [",", "ml,ai", 'x"y']


@pytest.mark.parametrize("tool", ["read_note", "read_many", "list_notes", "search_notes"])
def test_mcp_tags_round_trip(tagged_vault, monkeypatch, tool):
    pytest.importorskip("mcp")
    from hyperresearch.mcp import server

    monkeypatch.setattr(server, "_vault", tagged_vault)
    data = json.loads({
        "read_note": lambda: server.read_note("comma-tag"),
        "read_many": lambda: server.read_many("comma-tag,no-tags"),
        "list_notes": server.list_notes,
        "search_notes": lambda: server.search_notes("Comma"),
    }[tool]())
    notes = [data] if tool == "read_note" else data["notes"] if tool == "read_many" else data
    note = next(n for n in notes if n["id"] == "comma-tag")
    assert sorted(note["tags"]) == [",", "ml,ai", 'x"y']
    for note in notes:
        if note["id"] == "no-tags":
            assert note["tags"] == []
