"""Fetched titles, URLs and API records print literally in human output.

They were interpolated into Rich markup, so a title holding a closing tag
such as "[/y]" raised MarkupError: `fetch` exited 1 after saving the note,
`fetch-batch` aborted in Phase 1 with notes on disk and no sources rows (the
rerun duplicated them), and `scholar search` crashed on a title like
"Carbon isotope ratios [/mil] in estuaries". Text like "list[int]" lost its
brackets silently. Offline: fake providers only.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.scholar.base import Paper, SearchProvider
from hyperresearch.web.base import WebResult

runner = CliRunner()

TEXT = "River sediments settle in estuaries over long periods of time. " * 20
TITLES = {
    "https://site.example.org/a": "River Sediments",
    "https://site.example.org/q?x[/y]": "Query page x[/y]",
    "https://site.example.org/t": "Typing with list[int] and [bold]",
}


class _TitledProvider:
    name = "fake-titles"

    def fetch(self, url: str) -> WebResult:
        return WebResult(url=url, title=TITLES[url], content=TEXT)


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Markup"])
    assert result.exit_code == 0
    root = tmp_path / "kb"
    os.chdir(root)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _TitledProvider())
    return root


def _source_count(root: Path) -> int:
    conn = sqlite3.connect(root / ".hyperresearch" / "hyperresearch.db")
    try:
        return conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
    finally:
        conn.close()


def test_fetch_prints_a_title_with_a_closing_tag(vault_dir: Path):
    url = "https://site.example.org/q?x[/y]"
    result = runner.invoke(app, ["fetch", url])
    assert result.exit_code == 0, result.output
    assert "Saved: Query page x[/y]" in result.output
    assert f"Source: {url}" in result.output

    again = runner.invoke(app, ["fetch", url])
    assert again.exit_code == 1
    assert f"Already fetched: {url}" in again.output


def test_fetch_batch_finishes_and_records_every_source(vault_dir: Path):
    result = runner.invoke(app, ["fetch-batch", *TITLES])
    assert result.exit_code == 0, result.output
    assert "+ Query page x[/y]" in result.output
    assert "+ Typing with list[int] and [bold]" in result.output
    assert "3 notes created" in result.output
    assert _source_count(vault_dir) == 3

    rerun = runner.invoke(app, ["fetch-batch", *TITLES])
    assert rerun.exit_code == 0, rerun.output
    assert "Skip: https://site.example.org/q?x[/y]" in rerun.output
    assert _source_count(vault_dir) == 3


def test_fetch_batch_prints_a_failure_whose_error_has_brackets(vault_dir: Path, monkeypatch):
    class _Failing:
        name = "fake-fail"

        def fetch(self, url: str) -> WebResult:
            raise RuntimeError("upstream said [/oops]")

    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: _Failing())
    result = runner.invoke(app, ["fetch-batch", "https://site.example.org/q?x[/y]"])
    assert result.exit_code == 0, result.output
    assert "upstream said [/oops]" in result.output


def _install_scholar(monkeypatch, papers: tuple[Paper, ...]) -> None:
    from hyperresearch.cli import scholar_cmd
    from hyperresearch.scholar import registry

    def search(self, conn, query, limit, *, fresh=False):
        return list(papers)

    cls = type(
        "Fake_openalex",
        (SearchProvider,),
        {"slug": "openalex", "label": "Fake", "covers": "x", "needs_key": False,
         "key_env": (), "search": search},
    )
    monkeypatch.setattr(registry, "get_providers", lambda *a, **k: [cls()])
    monkeypatch.setattr(registry, "unavailable_notes", lambda scope: [])
    monkeypatch.setattr(scholar_cmd, "_open_cache", lambda: (None, None))


def test_scholar_search_prints_api_records_literally(monkeypatch):
    paper = Paper(
        title="Carbon isotope ratios [/mil] in estuaries",
        source="openalex",
        authors=("Smith, [J.]",),
        venue="Journal of [Marine] Chemistry",
        doi="10.1/x[1]",
        url="https://example.org/w[2]",
        year=2022,
    )
    _install_scholar(monkeypatch, (paper,))

    result = runner.invoke(app, ["scholar", "search", "carbon [/q]"])
    assert result.exit_code == 0, result.output
    out = result.output
    assert "Carbon isotope ratios [/mil] in estuaries" in out
    assert "Smith, [J.]" in out
    assert "Journal of [Marine] Chemistry" in out
    assert "doi:10.1/x[1]" in out
    assert "https://example.org/w[2]" in out


def test_scholar_search_no_results_echoes_the_query(monkeypatch):
    _install_scholar(monkeypatch, ())
    result = runner.invoke(app, ["scholar", "search", "nothing [/q] here"])
    assert result.exit_code == 0, result.output
    assert "'nothing [/q] here'" in result.output


def test_json_mode_was_never_affected(vault_dir: Path):
    result = runner.invoke(app, ["fetch-batch", *TITLES, "--json"])
    assert result.exit_code == 0, result.output
    titles = {n["title"] for n in json.loads(result.stdout)["data"]["notes_created"]}
    assert titles == set(TITLES.values())
