"""MCP metadata edits update the timestamp used by recent-note listings."""

import json
from datetime import UTC, datetime

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.frontmatter import parse_frontmatter
from hyperresearch.core.note import write_note

runner = CliRunner()


def test_mcp_edit_becomes_the_most_recent_note(tmp_vault, monkeypatch):
    server = pytest.importorskip("hyperresearch.mcp.server")
    monkeypatch.setattr(server, "_vault", tmp_vault)
    monkeypatch.chdir(tmp_vault.root)
    path = write_note(tmp_vault.notes_dir, "Gamma Note", body="Body\n")
    write_note(tmp_vault.notes_dir, "Beta Note")
    result = runner.invoke(app, ["note", "update", "beta-note", "--summary", "edited by CLI"])
    assert result.exit_code == 0, result.output
    assert json.loads(server.list_notes())[0]["id"] == "beta-note"

    before = datetime.now(UTC)
    result = json.loads(server.update_note("gamma-note", summary="edited by MCP, later"))
    after = datetime.now(UTC)
    assert result["ok"] is True
    meta, body = parse_frontmatter(path.read_text())
    assert meta.updated is not None
    assert before <= meta.updated <= after
    assert body == "Body\n"
    assert json.loads(server.read_note("gamma-note"))["updated"] is not None
    assert json.loads(server.list_notes())[0]["id"] == "gamma-note"


def test_mcp_noop_does_not_write_or_bump_updated(tmp_vault, monkeypatch):
    server = pytest.importorskip("hyperresearch.mcp.server")
    monkeypatch.setattr(server, "_vault", tmp_vault)
    path = write_note(tmp_vault.notes_dir, "Alpha Note", tags=["keep"])
    before = path.read_bytes()
    result = json.loads(server.update_note("alpha-note", add_tags="keep"))
    assert result["ok"] is True
    assert result["data"]["changes"] == []
    assert path.read_bytes() == before
