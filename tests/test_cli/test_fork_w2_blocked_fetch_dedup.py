"""Repeated blocked fetches share one escalation per URL and run tag."""

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.escalation import enqueue, resolve
from hyperresearch.web.base import WebResult

runner = CliRunner()
URL = "https://example.org/blocked"


@pytest.mark.parametrize("command", ["fetch", "fetch-batch"])
@pytest.mark.parametrize("title", ["Sign in to continue", "Just a moment..."])
@pytest.mark.parametrize("tag", [None, "run-one"])
def test_repeated_blocked_fetches_queue_once(tmp_vault, monkeypatch, command, title, tag):
    monkeypatch.chdir(tmp_vault.root)

    class Provider:
        name = "offline"

        def fetch(self, url):
            return WebResult(url=url, title=title, content="Research content. " * 40)

    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: Provider())
    monkeypatch.setattr("hyperresearch.core.oa.rescue_full_text", lambda *a, **k: (None, None))
    args = [command, URL, "--json"] + (["--tag", tag] if tag else [])
    for _ in range(3):
        result = runner.invoke(app, args)
        assert result.exit_code == (1 if command == "fetch" else 0), result.output
    rows = tmp_vault.db.execute("SELECT url, vault_tag FROM escalations").fetchall()
    assert [(r["url"], r["vault_tag"]) for r in rows] == [(URL, tag)]


@pytest.mark.parametrize("status", ["queued", "in_progress", "needs_human", "fetched", "abandoned"])
def test_null_tag_dedup_preserves_existing_state(tmp_vault, status):
    conn = tmp_vault.db
    item_id = enqueue(conn, URL, "login_wall", detail="original")
    if status == "in_progress":
        from hyperresearch.core.escalation import claim_next
        claim_next(conn, "browser")
    elif status != "queued":
        resolve(conn, item_id, status)
    before = dict(conn.execute("SELECT * FROM escalations WHERE id = ?", (item_id,)).fetchone())
    assert enqueue(conn, URL, "bot_block", detail="retry") is None
    assert dict(conn.execute("SELECT * FROM escalations WHERE id = ?", (item_id,)).fetchone()) == before
    assert enqueue(conn, URL, "login_wall", vault_tag="other-run") is not None
    assert enqueue(conn, URL, "login_wall", vault_tag="") is not None
    assert enqueue(conn, URL + "/other", "login_wall") is not None
    assert conn.execute("SELECT COUNT(*) FROM escalations").fetchone()[0] == 4
