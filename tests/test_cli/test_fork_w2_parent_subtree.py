"""Parent subtrees treat topic names as literals, not SQL patterns."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import read_note, write_note

runner = CliRunner()


@pytest.mark.parametrize("parent,other", [
    ("deep_learning", "deepXlearning"),
    ("100%", "100percent"),
    ("back\\slash", "backslash"),
    ("Mixed", "mixed"),
])
@pytest.mark.parametrize("command", ["batch", "topic", "export", "mcp"])
def test_parent_subtree_is_literal(tmp_vault, monkeypatch, parent, other, command):
    monkeypatch.chdir(tmp_vault.root)
    paths = {}
    for title, topic in [("Exact", parent), ("Child", parent + "/rnn"),
                         ("Unrelated", other + "/rnn"), ("Prefix", parent + "extra/rnn")]:
        paths[title] = write_note(tmp_vault.notes_dir, title, parent=topic, body="body")
    tmp_vault.auto_sync()
    if command == "mcp":
        from hyperresearch.mcp import server
        monkeypatch.setattr(server, "_get_vault", lambda: tmp_vault)
        notes = json.loads(server.list_notes(parent=parent))
        ids = {n["id"] for n in notes}
    else:
        args = {
            "batch": ["batch", "set-status", "archive", "--parent", parent, "--json"],
            "topic": ["topic", "show", parent, "--json"],
            "export": ["export", "vault", str(tmp_vault.root.parent / "export"),
                       "--parent", parent, "--json"],
        }[command]
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)["data"]
        ids = set(data["modified"]) if command == "batch" else {
            n["id"] for n in data["notes" if command == "topic" else "exported"]
        }
    assert ids == {"exact", "child"}
    if command == "batch":
        assert read_note(paths["Unrelated"], tmp_vault.root).meta.status == "draft"
        assert read_note(paths["Prefix"], tmp_vault.root).meta.status == "draft"
