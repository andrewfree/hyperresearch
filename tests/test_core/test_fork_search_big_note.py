"""Search over a very large note returns quickly and still shows a snippet.

FTS5's snippet() scores every candidate window against every phrase
instance in the body, so its cost grows with the square of the matches: one
5 MB note made a prefix query take minutes. Long bodies now get their
snippet from a bounded excerpt around the first match.
"""

from __future__ import annotations

import time

import pytest

from hyperresearch.search.fts import search_fts

# Every token starts with w1, so the prefix query w1* matches all 40,000.
DUMP = "Start of the dump. " + " ".join(f"w1{i % 10}" for i in range(40_000)) + " needle at the end."
SMALL = "A small note about w1 and attention, with a needle."


@pytest.fixture
def big_vault(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    write_note(tmp_vault.notes_dir, "Big Dump", body=DUMP)
    write_note(tmp_vault.notes_dir, "Small Note", body=SMALL)
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    return tmp_vault


def _snippets(vault, query):
    return {r["id"]: r["snippet"] for r in search_fts(vault.db, query)}


def test_prefix_query_over_a_big_note_is_fast(big_vault):
    start = time.perf_counter()
    snippets = _snippets(big_vault, "w1")
    elapsed = time.perf_counter() - start
    # Unbounded, snippet() took about 10 s here; the excerpt takes well under 1 s.
    assert elapsed < 2.0, f"search took {elapsed:.1f}s"
    assert set(snippets) == {"big-dump", "small-note"}
    assert ">>>w1" in snippets["big-dump"]


def test_big_note_snippet_is_taken_around_a_late_match(big_vault):
    snippet = _snippets(big_vault, "needle")["big-dump"]
    assert ">>>needle<<<" in snippet
    assert snippet.startswith("...")


def test_big_note_matched_only_by_title_shows_its_start(big_vault):
    snippet = _snippets(big_vault, "dump")["big-dump"]
    assert snippet.startswith("Start of the >>>dump<<<")


def test_small_note_snippet_is_unchanged(big_vault):
    # Bodies under the bound keep FTS5's own snippet() over the whole body.
    expected = big_vault.db.execute(
        "SELECT snippet(notes_fts, 2, '>>>', '<<<', '...', 64) FROM notes_fts "
        "WHERE notes_fts MATCH ? AND id = 'small-note'",
        ('"needle"*',),
    ).fetchone()[0]
    assert _snippets(big_vault, "needle")["small-note"] == expected
