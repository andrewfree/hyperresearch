"""fetch-batch applies the same gates as fetch, and accounts for what they refuse.

The batch result loop only checked for a login wall, so empty pages, binary
garbage, error pages and [junk] extra_junk_signals were saved as notes that
`fetch` rejects as JUNK_CONTENT. A login-walled URL was dropped with no
failed_urls entry and no escalation, where `fetch` answers
AUTH_REQUIRED_ESCALATED. Offline: a fake provider serves every page.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult

runner = CliRunner()

GOOD = "https://site.example.org/article"
EMPTY = "https://site.example.org/empty"
BINARY = "https://site.example.org/binary"
LOGIN = "https://site.example.org/members"
GUIDE = "https://site.example.org/guide"

ARTICLE = "River sediments settle in estuaries over long periods of time. " * 20
random.seed(42)
GARBAGE = bytes(random.getrandbits(8) for _ in range(4000)).decode("utf-8", errors="replace")


class _GatedPagesProvider:
    name = "fake-gates"

    def fetch(self, url: str) -> WebResult:
        if url == EMPTY:
            return WebResult(url=url, title="Empty", content="")
        if url == BINARY:
            return WebResult(url=url, title="binary.html", content=GARBAGE)
        if url == LOGIN:
            return WebResult(url=url, title="Sign in to continue", content=ARTICLE)
        if url == GUIDE:
            return WebResult(url=url, title="A Field Guide", content=ARTICLE)
        return WebResult(url=url, title="River Sediments", content=ARTICLE)


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Gates"])
    assert result.exit_code == 0
    root = tmp_path / "kb"
    os.chdir(root)
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _GatedPagesProvider()
    )
    return root


def _note_files(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "research" / "notes").glob("*.md"))


def _escalated_urls(root: Path) -> list[str]:
    conn = sqlite3.connect(root / ".hyperresearch" / "hyperresearch.db")
    try:
        return [r[0] for r in conn.execute("SELECT url FROM escalations ORDER BY url")]
    finally:
        conn.close()


def _batch(*urls: str) -> dict:
    result = runner.invoke(app, ["fetch-batch", *urls, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["data"]


def test_fetch_and_fetch_batch_agree_that_empty_and_binary_pages_are_junk(vault_dir: Path):
    for url in (EMPTY, BINARY):
        single = runner.invoke(app, ["fetch", url, "--json"])
        assert json.loads(single.stdout)["error_code"] == "JUNK_CONTENT"

    data = _batch(GOOD, EMPTY, BINARY)

    assert [n["url"] for n in data["notes_created"]] == [GOOD]
    failed = {f["url"]: f for f in data["failed_urls"]}
    assert set(failed) == {EMPTY, BINARY}
    assert {f["phase"] for f in failed.values()} == {"junk"}
    assert "Empty or near-empty content" in failed[EMPTY]["error"]
    assert "binary" in failed[BINARY]["error"]
    assert _note_files(vault_dir) == ["river-sediments.md"]
    assert _escalated_urls(vault_dir) == [], "content-quality junk is not escalated"


def test_extra_junk_signals_refuse_the_page_and_queue_it(vault_dir: Path):
    cfg = vault_dir / ".hyperresearch" / "config.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8").replace(
            "extra_junk_signals = []", 'extra_junk_signals = ["field guide"]'
        ),
        encoding="utf-8",
    )

    data = _batch(GUIDE)

    assert data["notes_created"] == []
    [failure] = data["failed_urls"]
    assert failure["url"] == GUIDE and failure["phase"] == "junk"
    assert "Bot detection page" in failure["error"]
    assert "Queued for browser-lane escalation" in failure["error"]
    assert _escalated_urls(vault_dir) == [GUIDE]


def test_a_login_walled_url_is_reported_failed_and_queued_for_escalation(vault_dir: Path):
    data = _batch(LOGIN, GOOD)

    assert data["total_fetched"] == 1
    [failure] = data["failed_urls"]
    assert failure["url"] == LOGIN
    assert failure["phase"] == "auth"
    assert "login wall: Sign in to continue" in failure["error"]
    assert "Queued for browser-lane escalation" in failure["error"]
    assert _escalated_urls(vault_dir) == [LOGIN]


def test_human_output_counts_a_gated_url_as_failed(vault_dir: Path):
    result = runner.invoke(app, ["fetch-batch", LOGIN, EMPTY, GOOD])
    assert result.exit_code == 0, result.output
    assert "Auth required" in result.output
    assert "1 notes created" in result.output
    assert "2 failed" in result.output
