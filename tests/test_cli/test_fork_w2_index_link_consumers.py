"""Generated index links do not supply connectivity or promotion evidence."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import read_note, write_note
from hyperresearch.indexgen.generator import IndexGenerator

runner = CliRunner()


def _run(*args):
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)["data"]


@pytest.fixture
def indexed_vault(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    for title, body in [("Lonely", "alone " * 120), ("Linker", "[[target]]"),
                        ("Target", "target " * 120)]:
        write_note(tmp_vault.notes_dir, title, body=body, status="review")
    tmp_vault.auto_sync()
    IndexGenerator(tmp_vault).build_all()
    write_note(tmp_vault.index_dir, "Generated", note_type="index", body="[[missing-index-target]]")
    tmp_vault.auto_sync()
    return tmp_vault


def test_status_ignores_generated_links(indexed_vault):
    assert _run("status")["graph"] == {"total_links": 1, "broken_links": 0, "orphan_notes": 1}
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "Orphans: 1" in result.output


def test_repair_uses_note_links_for_promotion_and_health(indexed_vault):
    data = _run("repair", "--no-stub", "--no-enrich", "--no-index", "--no-docs")
    assert data["promoted"] == 1
    assert read_note(indexed_vault.notes_dir / "lonely.md", indexed_vault.root).meta.status == "review"
    assert read_note(indexed_vault.notes_dir / "target.md", indexed_vault.root).meta.status == "evergreen"
    assert data["health"] == {"total_notes": 3, "broken_links": 0, "orphans": 1}


def test_watch_lint_ignores_generated_links(indexed_vault, capsys):
    from hyperresearch.cli.watch import _quick_lint
    _quick_lint(indexed_vault)
    output = capsys.readouterr().out
    assert "1 orphans" in output
    assert "broken links" not in output


@pytest.mark.parametrize("tool", ["backlinks", "hubs", "status", "orphans", "broken"])
def test_mcp_ignores_generated_links(indexed_vault, monkeypatch, tool):
    from hyperresearch.mcp import server
    monkeypatch.setattr(server, "_get_vault", lambda: indexed_vault)
    if tool == "backlinks":
        assert json.loads(server.get_backlinks("lonely"))["backlinks"] == []
        assert [b["source_id"] for b in json.loads(server.get_backlinks("target"))["backlinks"]] == ["linker"]
    elif tool == "hubs":
        assert json.loads(server.get_hubs()) == [{"id": "target", "title": "Target", "inbound_links": 1}]
    elif tool == "status":
        data = json.loads(server.vault_status())
        assert data["total_links"] == 1
        assert data["broken_links"] == 0
    elif tool == "orphans":
        assert [i["note_id"] for i in json.loads(server.lint_vault("orphaned-notes"))["issues"]] == ["lonely"]
    else:
        assert json.loads(server.lint_vault("broken-links"))["issues"] == []


def test_embed_sync_preserves_config_section_name(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["embed", "sync"])
    assert result.exit_code == 1
    assert "[embeddings]" in result.output
