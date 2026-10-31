"""Removing a note must still refresh the links that pointed to it."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note


def test_remove_marks_incoming_link_unresolved(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, "Target")
    write_note(tmp_vault.notes_dir, "Source", body="See [[target]].")
    tmp_vault.auto_sync()
    result = CliRunner().invoke(app, ["note", "rm", "target", "--force", "--json"])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(app, ["graph", "outlinks", "source", "--json"])
    assert result.exit_code == 0, result.output
    link = json.loads(result.output)["data"]["outlinks"][0]
    assert link["target_id"] is None
    assert link["resolved"] is False


@pytest.mark.parametrize("ref", ["target", "iv"])
def test_remove_resolves_incoming_link_to_remaining_alias(tmp_vault, monkeypatch, ref):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, "Original", note_id=ref)
    write_note(tmp_vault.notes_dir, "Fallback", extra_frontmatter={"aliases": [ref]})
    write_note(tmp_vault.notes_dir, "Source", body=f"See [[{ref}]].")
    tmp_vault.auto_sync()
    result = CliRunner().invoke(app, ["note", "rm", ref, "--force", "--json"])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(app, ["graph", "outlinks", "source", "--json"])
    assert result.exit_code == 0, result.output
    links = json.loads(result.output)["data"]["outlinks"]
    assert len(links) == 1
    assert links[0]["target_id"] == "fallback"


def test_remove_drops_reference_that_is_only_a_footnote_now(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, "IV", note_id="iv")
    write_note(tmp_vault.notes_dir, "Source", body="See [[iv]] and [[missing-topic]].")
    tmp_vault.auto_sync()
    result = CliRunner().invoke(app, ["note", "rm", "iv", "--force", "--json"])
    assert result.exit_code == 0, result.output
    result = CliRunner().invoke(app, ["graph", "outlinks", "source", "--json"])
    assert result.exit_code == 0, result.output
    links = json.loads(result.output)["data"]["outlinks"]
    assert [link["target_ref"] for link in links] == ["missing-topic"]
