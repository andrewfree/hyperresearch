"""`escalation ingest` completes a claimed item, and only a claimed item.

ingest wrote the note and resolved the item without looking at its status, so
a retried ingest of an item already fetched wrote a second note (`paper-2`)
and repointed the item at it while the sources row still named the first,
and an item nobody had claimed (queued, or waiting on the human) could be
ingested too. The item must be in_progress, and only one ingest can move it
to fetched.
"""

from __future__ import annotations

import json
import sqlite3

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.escalation import claim_next, enqueue, resolve

runner = CliRunner()

URL = "https://example.org/paper"


@pytest.fixture
def vault(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    return tmp_vault


@pytest.fixture
def body(vault):
    path = vault.root / "body.md"
    path.write_text("Extracted page text with plenty of real words in it.\n", encoding="utf-8")
    return path


def _ingest(item_id: int, body, title: str = "Paper"):
    return runner.invoke(
        app,
        ["escalation", "ingest", str(item_id), "--title", title, "--body-file", str(body), "--json"],
    )


def _item(conn, item_id: int) -> dict:
    return dict(conn.execute("SELECT * FROM escalations WHERE id = ?", (item_id,)).fetchone())


def _notes(vault) -> list[str]:
    return sorted(p.name for p in vault.notes_dir.glob("*.md"))


def _source_note_ids(vault) -> list[str]:
    return [r["note_id"] for r in vault.db.execute("SELECT note_id FROM sources WHERE url = ?", (URL,))]


def test_reingesting_a_fetched_item_writes_no_second_note(vault, body):
    item_id = enqueue(vault.db, URL, "login_wall")
    claim_next(vault.db, "tester")
    first = _ingest(item_id, body)
    assert first.exit_code == 0, first.output
    assert json.loads(first.stdout)["data"]["note_id"] == "paper"

    again = _ingest(item_id, body)
    assert again.exit_code == 1
    payload = json.loads(again.stdout)
    assert payload["ok"] is False
    assert payload["error_code"] == "ALREADY_RESOLVED"
    assert "note 'paper'" in payload["error"]
    assert _notes(vault) == ["paper.md"]
    assert _item(vault.db, item_id)["note_id"] == "paper"
    assert _source_note_ids(vault) == ["paper"]


@pytest.mark.parametrize("status", ["queued", "needs_human"])
def test_an_unclaimed_item_is_refused(vault, body, status):
    item_id = enqueue(vault.db, URL, "captcha")
    if status == "needs_human":
        claim_next(vault.db, "tester")
        resolve(vault.db, item_id, "needs_human", detail="solve the CAPTCHA")

    result = _ingest(item_id, body, title="Unclaimed")
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "NOT_CLAIMED"
    assert f"#{item_id} is {status}" in payload["error"]
    assert _notes(vault) == []
    assert _item(vault.db, item_id)["status"] == status
    assert _source_note_ids(vault) == []


def test_an_abandoned_item_is_refused(vault, body):
    item_id = enqueue(vault.db, URL, "bot_block")
    claim_next(vault.db, "tester")
    resolve(vault.db, item_id, "abandoned", detail="dead page")

    result = _ingest(item_id, body)
    assert result.exit_code == 1
    assert json.loads(result.stdout)["error_code"] == "ALREADY_RESOLVED"
    assert _notes(vault) == []
    assert _item(vault.db, item_id)["status"] == "abandoned"


def test_an_ingest_that_loses_the_race_keeps_the_winners_note(vault, body, monkeypatch):
    """Two ingests of one claimed item both pass the status check; the one
    that resolves second removes its own note instead of repointing the item."""
    import hyperresearch.core.note as note_mod

    item_id = enqueue(vault.db, URL, "login_wall")
    claim_next(vault.db, "tester")
    real_write_note = note_mod.write_note

    def write_while_the_other_ingest_finishes(*args, **kwargs):
        path = real_write_note(*args, **kwargs)
        other = sqlite3.connect(vault.db_path)  # the other ingest's own connection
        other.row_factory = sqlite3.Row
        resolve(other, item_id, "fetched", note_id="winner")
        other.close()
        return path

    monkeypatch.setattr(note_mod, "write_note", write_while_the_other_ingest_finishes)
    result = _ingest(item_id, body)

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "ALREADY_RESOLVED"
    assert "note 'winner'" in payload["error"]
    assert _notes(vault) == []
    assert vault.db.execute("SELECT id FROM notes WHERE id = 'paper'").fetchone() is None
    assert _item(vault.db, item_id)["note_id"] == "winner"
    assert _source_note_ids(vault) == []
