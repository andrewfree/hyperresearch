"""A long note re-synced while a search runs does not crash the search.

A body over the snippet bound gets its snippet from a second query that reads
the FTS row by rowid after the search query returned. Sync rewrites a note's
FTS row (delete, then insert under a new rowid), so a sync from another
process (watch, the MCP server) landing between the two queries left that
read with no row, and the search failed with a TypeError.
"""

from __future__ import annotations

import pytest

from hyperresearch.search.fts import search_fts

BIG = "Start. " + " ".join(f"w{i % 50}" for i in range(6_000)) + " needle at the end."


@pytest.fixture
def big_vault(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    write_note(tmp_vault.notes_dir, "Big Dump", body=BIG)
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    # A later row, so the rewritten big row cannot get its old rowid back.
    write_note(tmp_vault.notes_dir, "Small Note", body="Unrelated.")
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    return tmp_vault


class _ResyncAfterSearch:
    """Runs the search query, then rewrites the big note's FTS row the way
    sync does before search_fts reads anything else."""

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=()):
        cur = self._conn.execute(sql, params)
        if "LIMIT ? OFFSET ?" not in sql:
            return cur
        rows = cur.fetchall()
        old = self._conn.execute(
            "SELECT id, title, body_plain, tags, aliases FROM notes_fts WHERE id = 'big-dump'"
        ).fetchone()
        self._conn.execute("DELETE FROM notes_fts WHERE id = 'big-dump'")
        self._conn.execute(
            "INSERT INTO notes_fts (id, title, body_plain, tags, aliases) VALUES (?, ?, ?, ?, ?)",
            tuple(old),
        )
        return _Rows(rows)


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


def test_search_survives_a_resync_between_queries(big_vault):
    results = search_fts(_ResyncAfterSearch(big_vault.db), "needle")
    assert [r["id"] for r in results] == ["big-dump"]
    assert isinstance(results[0]["snippet"], str)
