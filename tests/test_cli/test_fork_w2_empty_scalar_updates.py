"""Falsy YAML scalars and sequences are not editable metadata mappings."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note

runner = CliRunner()


@pytest.mark.parametrize("tool", ["mcp", "cli"])
@pytest.mark.parametrize("yaml_value", ["[]", "false", "0", "''"])
def test_nonmapping_frontmatter_is_preserved(tmp_vault, monkeypatch, tool, yaml_value):
    path = write_note(tmp_vault.notes_dir, "Alpha Note", tags=["keep"])
    tmp_vault.auto_sync()
    path.write_text(f"---\n{yaml_value}\n---\n\nBody\n")
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
