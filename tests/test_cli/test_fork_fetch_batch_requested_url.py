"""fetch-batch records and dedups sources on the URL that was asked for.

The builtin provider returns the post-redirect URL as ``result.url``, and
fetch-batch used that for the note's ``source:`` and the sources row. The
requested URL was never recorded, so the next batch run missed the duplicate
check and wrote another note. The same URL given twice in one batch was
fetched twice, and Phase 3 never noticed that its INSERT OR IGNORE was a
no-op, so the second note had no sources row. Offline: fake providers only.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.frontmatter import parse_frontmatter
from hyperresearch.web.base import WebResult

runner = CliRunner()

REQUESTED = "https://site.example.org/go/article"
LANDED = "https://site.example.org/article"
BODY = "River sediments settle in estuaries over long periods of time. " * 20


class _RedirectingProvider:
    """Like the builtin provider: ``result.url`` is where the redirect landed."""

    name = "fake-redirect"

    def __init__(self):
        self.calls: list[str] = []

    def fetch(self, url: str) -> WebResult:
        self.calls.append(url)
        return WebResult(url=url.replace("/go/", "/"), title="River Sediments", content=BODY)


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Requested URL"])
    assert result.exit_code == 0
    root = tmp_path / "kb"
    os.chdir(root)
    return root


def _sources(root: Path) -> list[tuple[str, str | None]]:
    conn = sqlite3.connect(root / ".hyperresearch" / "hyperresearch.db")
    try:
        return conn.execute("SELECT url, note_id FROM sources ORDER BY url").fetchall()
    finally:
        conn.close()


def _note_files(root: Path) -> list[str]:
    return sorted(p.name for p in (root / "research" / "notes").glob("*.md"))


def test_batch_records_the_requested_url_and_a_rerun_skips_it(vault_dir: Path, monkeypatch):
    prov = _RedirectingProvider()
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: prov)

    first = runner.invoke(app, ["fetch-batch", REQUESTED, "--json"])
    assert first.exit_code == 0, first.output
    created = json.loads(first.stdout)["data"]["notes_created"]
    assert [n["url"] for n in created] == [REQUESTED]
    note_id = created[0]["note_id"]
    assert _sources(vault_dir) == [(REQUESTED, note_id)]
    meta, _ = parse_frontmatter(
        (vault_dir / "research" / "notes" / f"{note_id}.md").read_text(encoding="utf-8")
    )
    assert meta.source == REQUESTED

    second = runner.invoke(app, ["fetch-batch", REQUESTED, "--json"])
    assert second.exit_code == 0, second.output
    data = json.loads(second.stdout)["data"]
    assert data["notes_created"] == []
    assert data["skipped"] == 1
    assert _note_files(vault_dir) == [f"{note_id}.md"]
    assert prov.calls == [REQUESTED], "the rerun must not fetch an already-recorded URL"


class _OutOfOrderBatchProvider:
    """fetch_many answers in completion order, each result naming its input."""

    name = "fake-many"

    def fetch(self, url: str) -> WebResult:  # pragma: no cover - not used
        raise AssertionError("fetch_many should serve the whole batch")

    def fetch_many(self, urls):
        return [
            WebResult(
                url=u.replace("/go/", "/"), requested_url=u,
                title=f"Page {u[-1]}", content=BODY,
            )
            for u in reversed(urls)
        ]


def test_fetch_many_results_are_recorded_under_their_requested_url(vault_dir: Path, monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _OutOfOrderBatchProvider()
    )
    urls = ["https://site.example.org/go/a", "https://site.example.org/go/b"]

    result = runner.invoke(app, ["fetch-batch", *urls, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert sorted(n["url"] for n in data["notes_created"]) == urls
    assert data["failed_urls"] == []
    assert [url for url, _ in _sources(vault_dir)] == urls


def test_crawl4ai_batch_records_an_arxiv_abs_url_not_its_pdf_url(vault_dir: Path, monkeypatch):
    """The PDF lane rewrites /abs/ to /pdf/...pdf, and that is the result's url."""
    import socket

    import hyperresearch.web.crawl4ai_provider as c4
    from hyperresearch.core.config import FetchSettings

    monkeypatch.setattr(socket, "getaddrinfo", lambda h, p: [(2, 1, 6, "", ("93.184.216.34", 0))])
    monkeypatch.setattr(
        c4, "_fetch_pdf",
        lambda url, settings=None: WebResult(
            url=url.replace("/abs/", "/pdf/") + ".pdf", title="A Paper", content=BODY,
        ),
    )
    inst = c4.Crawl4AIProvider.__new__(c4.Crawl4AIProvider)
    inst._settings = FetchSettings()
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: inst)
    abs_url = "https://arxiv.org/abs/2401.00001"

    result = runner.invoke(app, ["fetch-batch", abs_url, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert [n["url"] for n in data["notes_created"]] == [abs_url]
    assert [url for url, _ in _sources(vault_dir)] == [abs_url]


def test_the_same_url_twice_in_one_batch_is_fetched_once(vault_dir: Path, monkeypatch):
    prov = _RedirectingProvider()
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: prov)

    result = runner.invoke(
        app, ["fetch-batch", "--stdin", "--json"], input=f"{REQUESTED}\r\n{REQUESTED}\n"
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert len(data["notes_created"]) == 1
    note_id = data["notes_created"][0]["note_id"]
    assert prov.calls == [REQUESTED]
    assert _note_files(vault_dir) == [f"{note_id}.md"]
    assert _sources(vault_dir) == [(REQUESTED, note_id)]


class _RacingProvider:
    """Another fetch records the URL while this batch is still fetching it."""

    name = "fake-race"

    def __init__(self, db_path: Path, winner_id: str):
        self.db_path = db_path
        self.winner_id = winner_id

    def fetch(self, url: str) -> WebResult:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO sources (url, note_id, domain, fetched_at, provider, content_hash) "
                "VALUES (?, ?, 'site.example.org', '2026-01-01T00:00:00+00:00', 'other', 'x')",
                (url, self.winner_id),
            )
            conn.commit()
        finally:
            conn.close()
        return WebResult(url=url, title="River Sediments", content=BODY)


def test_a_batch_that_loses_the_url_race_keeps_no_second_note(vault_dir: Path, monkeypatch):
    made = runner.invoke(app, ["note", "new", "Winner Note", "--body", "first", "--json"])
    assert made.exit_code == 0, made.output
    winner_id = json.loads(made.stdout)["data"]["id"]
    prov = _RacingProvider(vault_dir / ".hyperresearch" / "hyperresearch.db", winner_id)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: prov)

    result = runner.invoke(app, ["fetch-batch", REQUESTED, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["notes_created"] == []
    assert data["skipped"] == 1
    assert _note_files(vault_dir) == [f"{winner_id}.md"]
    assert _sources(vault_dir) == [(REQUESTED, winner_id)]
    conn = sqlite3.connect(vault_dir / ".hyperresearch" / "hyperresearch.db")
    try:
        ids = [r[0] for r in conn.execute("SELECT id FROM notes")]
    finally:
        conn.close()
    assert ids == [winner_id], "the losing note's row must be dropped by a re-sync"
