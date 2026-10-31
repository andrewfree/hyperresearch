"""Auto-generated index pages are not link sources for graph metrics.

`index build` (and `repair`, which runs it) writes pages such as _index,
_recent and _orphans that wiki-link every note they list. Graph queries read
those rows like real citations, so after a build no note was an orphan,
every listed note gained inbound links, and index pages took PageRank.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.vault import Vault

runner = CliRunner()


def _run(*args: str) -> dict:
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


@pytest.fixture
def built_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """lonely-one has no links; linker links to target; index pages are built."""
    root = tmp_path / "v"
    result = runner.invoke(app, ["init", str(root), "--name", "Graph Test"])
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(root)
    for title, body in [
        ("Lonely One", "No links."),
        ("Linker", "See [[target]]."),
        ("Target", "Linked to."),
    ]:
        _run("note", "new", title, "-b", body)
    _run("index", "build")
    _run("sync")
    return root


def test_index_links_stay_in_the_links_table(built_vault):
    # The viewer still follows an index page's links, so the rows are kept.
    db = Vault(built_vault).db
    n = db.execute("SELECT COUNT(*) FROM links WHERE source_id = '_index'").fetchone()[0]
    assert n > 0


def test_orphans_ignore_index_pages(built_vault):
    ids = {o["id"] for o in _run("graph", "orphans")["data"]}
    assert ids == {"lonely-one"}


def test_hubs_count_only_note_links(built_vault):
    hubs = {h["id"]: h["inbound_links"] for h in _run("graph", "hubs")["data"]}
    assert hubs == {"target": 1}


def test_backlinks_omit_index_pages(built_vault):
    assert _run("graph", "backlinks", "lonely-one")["data"]["backlinks"] == []
    sources = [b["source_id"] for b in _run("graph", "backlinks", "target")["data"]["backlinks"]]
    assert sources == ["linker"]


def test_lint_orphaned_notes_ignore_index_pages(built_vault):
    issues = _run("lint", "-r", "orphaned-notes")["data"]["issues"]
    assert [i["note_id"] for i in issues] == ["lonely-one"]


def test_rank_leaves_index_pages_out(built_vault):
    top = _run("graph", "rank", "--top", "50")["data"]["top"]
    ids = {t["id"] for t in top}
    assert ids == {"lonely-one", "linker", "target"}
    db = Vault(built_vault).db
    ranked_index = db.execute(
        "SELECT COUNT(*) FROM notes WHERE type = 'index' AND centrality_score IS NOT NULL"
    ).fetchone()[0]
    assert ranked_index == 0


def test_rank_clears_stale_index_scores(built_vault):
    # A vault ranked before index pages were excluded keeps their old score.
    db = Vault(built_vault).db
    db.execute("UPDATE notes SET centrality_score = 0.9 WHERE id = '_orphans'")
    db.commit()
    top = _run("graph", "rank", "--top", "50")["data"]["top"]
    assert "_orphans" not in {t["id"] for t in top}


@pytest.mark.parametrize("flags", [["--has-backlinks"], ["--min-inbound", "1"]])
def test_search_backlink_filters_ignore_index_pages(built_vault, flags):
    data = _run("search", "--type", "note", *flags, "--no-body")["data"]
    assert [r["id"] for r in data["results"]] == ["target"]


def test_rebuilt_orphans_and_most_linked_pages(built_vault):
    _run("index", "build")
    index_dir = built_vault / "research" / "index"
    orphans = (index_dir / "_orphans.md").read_text(encoding="utf-8")
    assert "[[lonely-one]]" in orphans
    most_linked = (index_dir / "_most-linked.md").read_text(encoding="utf-8")
    assert "[[target]] — Target (1 inbound links)" in most_linked
    assert "[[lonely-one]]" not in most_linked
