"""A batch command finishes the other notes when one cannot be rewritten.

Each subcommand looped over the notes calling _update_file_frontmatter with
no error handling, so one note whose frontmatter no longer parsed raised out
of the loop: the notes before it were rewritten, the ones after it were not,
the closing sync never ran, and --json printed a traceback and no envelope.
Every subcommand now goes through _batch_update_files, which records the
failure, carries on, syncs, and reports both lists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path / "v")]).exit_code == 0
    monkeypatch.chdir(tmp_path / "v")
    for title in ("Aaa", "Bbb", "Ccc"):
        result = runner.invoke(app, ["note", "new", title, "-b", "body", "-t", "old"])
        assert result.exit_code == 0, result.output
    bbb = tmp_path / "v" / "research" / "notes" / "bbb.md"
    # An unclosed quote: the YAML no longer parses.
    bbb.write_text(bbb.read_text(encoding="utf-8").replace("title: Bbb", 'title: "Bbb'), encoding="utf-8")
    return tmp_path / "v"


def _db():
    from hyperresearch.core.vault import Vault

    return Vault.discover().db


CASES = {
    "tag-add": (["tag-add", "newtag"], lambda db, nid: (nid, "newtag") in {
        (r["note_id"], r["tag"]) for r in db.execute("SELECT note_id, tag FROM tags")}),
    "tag-remove": (["tag-remove", "old"], lambda db, nid: (nid, "old") not in {
        (r["note_id"], r["tag"]) for r in db.execute("SELECT note_id, tag FROM tags")}),
    "set-status": (["set-status", "review"], lambda db, nid: db.execute(
        "SELECT status FROM notes WHERE id = ?", (nid,)).fetchone()["status"] == "review"),
    "deprecate": (["deprecate"], lambda db, nid: db.execute(
        "SELECT status FROM notes WHERE id = ?", (nid,)).fetchone()["status"] == "deprecated"),
    "set-parent": (["set-parent", "ml/nlp"], lambda db, nid: db.execute(
        "SELECT parent FROM notes WHERE id = ?", (nid,)).fetchone()["parent"] == "ml/nlp"),
}


@pytest.mark.parametrize("name", list(CASES))
def test_one_bad_note_does_not_stop_the_batch(root, name):
    args, applied = CASES[name]
    bbb = root / "research" / "notes" / "bbb.md"
    before = bbb.read_bytes()

    result = runner.invoke(app, ["batch", *args, "--json"])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "NOTES_NOT_UPDATED"
    data = envelope["data"]
    assert data["modified"] == ["aaa", "ccc"]
    [failure] = data["errors"]
    assert failure["id"] == "bbb"
    assert failure["path"] == "research/notes/bbb.md"
    assert failure["error"]

    # The notes after the bad one were rewritten, and the sync ran.
    assert bbb.read_bytes() == before
    db = _db()
    assert applied(db, "aaa")
    assert applied(db, "ccc")


def test_human_mode_names_the_failed_note(root):
    result = runner.invoke(app, ["batch", "tag-add", "newtag"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), result.exception
    assert "Added tag 'newtag' to 2 notes" in result.output
    assert "research/notes/bbb.md" in result.output


def test_all_good_notes_still_succeed(root):
    bbb = root / "research" / "notes" / "bbb.md"
    bbb.write_text(bbb.read_text(encoding="utf-8").replace('title: "Bbb', "title: Bbb"), encoding="utf-8")
    result = runner.invoke(app, ["batch", "set-status", "review", "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert envelope["count"] == 3
    assert envelope["data"]["modified"] == ["aaa", "bbb", "ccc"]
    assert "errors" not in envelope["data"]
