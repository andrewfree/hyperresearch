"""`research` prints search-result titles and the topic literally.

Like fetch and fetch-batch, research interpolated page titles into Rich
markup, so a title holding a closing tag such as "[/y]" raised MarkupError
after the first note was saved: the remaining results, the synthesis note
and the auto-link pass never ran. Its wiki-link lines lost their [[id]]
text the same way. Offline: a fake provider serves the search results.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult

runner = CliRunner()

BODY = "River sediments settle in estuaries over long periods of time. " * 20
RESULTS = [
    WebResult(url="https://site.example.org/a", title="Query page x[/y]", content=BODY),
    WebResult(url="https://site.example.org/b", title="Typing with list[int]", content=BODY),
]


class _SearchProvider:
    name = "fake-search"

    def search(self, query, max_results=5):
        return RESULTS

    def fetch(self, url):  # pragma: no cover - depth 0
        raise RuntimeError("no fetch in tests")


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Research Markup"]).exit_code == 0
    os.chdir(tmp_path / "kb")
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _SearchProvider())
    return tmp_path / "kb"


def test_research_prints_titles_with_brackets_and_finishes(vault_dir: Path):
    result = runner.invoke(app, ["research", "estuary [/q] sediments"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Researching: estuary [/q] sediments" in out
    assert "+ Query page x[/y]" in out
    assert "+ Typing with list[int]" in out
    assert "Synthesis: [[research-estuary-q-sediments]]" in out
    assert "[1 links] [[query-page-xy]] Query page x[/y]" in out

    conn = sqlite3.connect(vault_dir / ".hyperresearch" / "hyperresearch.db")
    try:
        assert conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 2
    finally:
        conn.close()
