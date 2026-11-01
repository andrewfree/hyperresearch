"""Viewer search distinguishes literal prompts from match markers."""

import pytest

from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.search.fts import search_fts
from hyperresearch.serve.server import HyperresearchHandler


@pytest.mark.parametrize("long_body", [False, True])
def test_viewer_highlights_only_matches(tmp_vault, long_body):
    body = "The doctest line >>> sum([1, 2]) <<< returns three for this widget."
    if long_body:
        body += " filler" * 3000
    write_note(tmp_vault.notes_dir, "Doctest", body=body)
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    handler = object.__new__(HyperresearchHandler)
    handler._db = tmp_vault.db
    responses = []
    handler._send = lambda *args: responses.append(args)

    handler._serve_search("widget")

    page = responses[0][1]
    assert "&gt;&gt;&gt;" in page
    assert "&lt;&lt;&lt;" in page
    assert page.count("<mark>") == page.count("</mark>") == 1
    assert "<mark>widget</mark>" in page
    assert ">>>widget<<<" in search_fts(tmp_vault.db, "widget")[0]["snippet"]


@pytest.mark.parametrize("long_body", [False, True])
def test_search_accepts_custom_snippet_markers(tmp_vault, long_body):
    write_note(tmp_vault.notes_dir, "Note", body="widget " + "filler " * (3000 if long_body else 1))
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))

    result = search_fts(tmp_vault.db, "widget", snippet_start="\x02", snippet_end="\x03")

    assert "\x02widget\x03" in result[0]["snippet"]
