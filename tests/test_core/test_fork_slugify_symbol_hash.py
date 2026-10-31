"""A title with no letters or digits gets an id hashed from the title itself.

slugify's fallback hashed the text after every character had been stripped,
so it always hashed '' and every punctuation-only or emoji-only title got
note-e3b0c442 (the start of sha256('')), then note-e3b0c442-2 and so on in
creation order, with a false "Similar note already exists" warning.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.models.note import slugify

runner = CliRunner()

EMPTY_HASH_ID = "note-e3b0c442"


def test_distinct_symbol_only_titles_get_distinct_ids():
    ids = {slugify(t) for t in ("!!!", "???", "🚀", "🚀🔥", "***", "-")}
    assert len(ids) == 6
    assert all(i.startswith("note-") for i in ids)
    assert EMPTY_HASH_ID not in ids


def test_fallback_is_stable_and_a_fixed_point():
    assert slugify("🚀") == slugify("🚀")
    assert slugify(" 🚀 ") == slugify("🚀")
    slug = slugify("🚀")
    assert slugify(slug) == slug


def test_note_new_symbol_titles_no_false_duplicate_warning(tmp_path: Path, monkeypatch):
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    monkeypatch.chdir(root)
    first = json.loads(runner.invoke(app, ["note", "new", "!!!", "--json"]).stdout)["data"]
    second = json.loads(runner.invoke(app, ["note", "new", "🚀🔥", "--json"]).stdout)["data"]
    assert first["id"] != second["id"]
    assert not second["id"].endswith("-2")
    assert "warning" not in second


def test_mcp_create_note_symbol_titles_get_their_own_ids(tmp_path: Path, monkeypatch):
    import pytest

    mcp = pytest.importorskip("hyperresearch.mcp.server")
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    monkeypatch.chdir(root)
    monkeypatch.setattr(mcp, "_vault", None)
    try:
        ids = [
            json.loads(mcp.create_note(title=t, body="x"))["data"]["note_id"]
            for t in ("🚀", "???")
        ]
    finally:
        mcp._vault = None
    assert ids == [slugify("🚀"), slugify("???")]
    assert len(set(ids)) == 2
