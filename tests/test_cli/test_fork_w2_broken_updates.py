"""Metadata edits refuse broken frontmatter without rewriting the file."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note

runner = CliRunner()


@pytest.mark.parametrize("tool", ["mcp", "cli"])
@pytest.mark.parametrize("broken", [
    "---\ntitle: Alpha Note\nid: alpha-note\ntags: [keep]\n\nBody\n",
    "---\n- not a mapping\n---\n\nBody\n",
    "---\ntitle: [invalid yaml\n---\n\nBody\n",
    "---\ntitle: Alpha Note\nstatus: invalid\n---\n\nBody\n",
])
def test_broken_frontmatter_is_not_overwritten(tmp_vault, monkeypatch, tool, broken):
    path = write_note(tmp_vault.notes_dir, "Alpha Note", tags=["keep"], body="Body\n")
    tmp_vault.auto_sync()
    path.write_text(broken)
    before = path.read_bytes()
    monkeypatch.chdir(tmp_vault.root)
    if tool == "mcp":
        server = pytest.importorskip("hyperresearch.mcp.server")
        monkeypatch.setattr(server, "_vault", tmp_vault)
        data = json.loads(server.update_note("alpha-note", add_tags="newtag"))
    else:
        result = runner.invoke(app, ["note", "update", "alpha-note", "--add-tag", "newtag", "--json"])
        assert result.exit_code == 1, result.output
        data = json.loads(result.output)
    assert data["ok"] is False
    assert data["error_code"] == "FRONTMATTER_BROKEN"
    assert path.read_bytes() == before
