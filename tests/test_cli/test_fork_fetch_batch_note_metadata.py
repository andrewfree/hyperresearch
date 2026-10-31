"""A fetch-batch note carries the metadata a `fetch` note does.

fetch-batch built its notes by hand and left out what `fetch` writes:
tier and content_type, and the raw PDF (research/raw/<id>.pdf
plus `raw_file:`). Batch PDFs then had no tier, and their bytes were thrown
away. Offline: a fake provider serves a stand-in PDF result.
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

PDF_BYTES = b"%PDF-1.4 stand-in for a paper"
TEXT = "Sediment transport in tidal estuaries is driven by asymmetric flows. " * 20


class _PaperProvider:
    name = "fake-pdf"

    def fetch(self, url: str) -> WebResult:
        return WebResult(
            url=url,
            title=f"Sediment Transport {url[-5]}",
            content=TEXT,
            raw_bytes=PDF_BYTES + url.encode(),
            raw_content_type="application/pdf",
        )


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Batch Metadata"])
    assert result.exit_code == 0
    root = tmp_path / "kb"
    os.chdir(root)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _PaperProvider())
    return root


def _meta(root: Path, note_id: str):
    meta, _ = parse_frontmatter(
        (root / "research" / "notes" / f"{note_id}.md").read_text(encoding="utf-8")
    )
    return meta


def test_batch_and_single_fetch_write_the_same_metadata(vault_dir: Path):
    single = runner.invoke(app, ["fetch", "https://repo.example.org/a.pdf", "--json"])
    assert single.exit_code == 0, single.output
    single_id = json.loads(single.stdout)["data"]["note_id"]

    batch = runner.invoke(app, ["fetch-batch", "https://repo.example.org/b.pdf", "--json"])
    assert batch.exit_code == 0, batch.output
    [entry] = json.loads(batch.stdout)["data"]["notes_created"]
    batch_id = entry["note_id"]

    for note_id in (single_id, batch_id):
        meta = _meta(vault_dir, note_id)
        assert meta.tier == "institutional", note_id
        assert meta.content_type == "paper", note_id
        assert meta.raw_file == f"raw/{note_id}.pdf", note_id

    raw = vault_dir / "research" / "raw" / f"{batch_id}.pdf"
    assert raw.read_bytes() == PDF_BYTES + b"https://repo.example.org/b.pdf"
    assert entry["raw_file"] == f"raw/{batch_id}.pdf"


class _RacingPaperProvider(_PaperProvider):
    """Another fetch records the URL while this batch is still fetching it."""

    def __init__(self, db_path: Path, winner_id: str):
        self.db_path = db_path
        self.winner_id = winner_id

    def fetch(self, url: str) -> WebResult:
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                "INSERT INTO sources (url, note_id, domain, fetched_at, provider, content_hash) "
                "VALUES (?, ?, 'repo.example.org', '2026-01-01T00:00:00+00:00', 'other', 'x')",
                (url, self.winner_id),
            )
            conn.commit()
        finally:
            conn.close()
        return super().fetch(url)


def test_a_race_loser_leaves_no_raw_file_behind(vault_dir: Path, monkeypatch):
    made = runner.invoke(app, ["note", "new", "Winner Note", "--body", "first", "--json"])
    assert made.exit_code == 0, made.output
    winner_id = json.loads(made.stdout)["data"]["id"]
    prov = _RacingPaperProvider(vault_dir / ".hyperresearch" / "hyperresearch.db", winner_id)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: prov)

    result = runner.invoke(app, ["fetch-batch", "https://repo.example.org/c.pdf", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["notes_created"] == []
    raw_dir = vault_dir / "research" / "raw"
    assert not raw_dir.exists() or list(raw_dir.iterdir()) == []
