"""Dropping dangling operators never turns a NOT into a match.

Operator queries drop an operator that lost its operand, and of two operators
left side by side keep the later one. A leading NOT was dropped too, so
'NOT foo AND bar' searched 'foo AND bar' and returned exactly the notes the
query excluded; 'bar NOT AND foo' became 'bar AND foo' the same way. FTS5
cannot express a NOT with no left operand, so such a query stays an error.
"""

from __future__ import annotations

import pytest

from hyperresearch.search.fts import SearchQueryError, preprocess_query, search_fts


@pytest.fixture
def not_vault(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    write_note(tmp_vault.notes_dir, "Both Words", body="zebra and walrus together.")
    write_note(tmp_vault.notes_dir, "Walrus Only", body="walrus alone here.")
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    return tmp_vault


@pytest.mark.parametrize("query", [
    "NOT zebra AND walrus",
    "(NOT zebra) AND walrus",
    "walrus AND (NOT zebra)",
    "walrus NOT AND zebra",
    "walrus NOT OR zebra",
    "- NOT zebra AND walrus",
])
def test_not_with_an_operand_is_never_dropped(not_vault, query):
    # FTS5 has no NOT without a left operand, so the query is rejected as it
    # was before dangling operators were dropped, never run without the NOT.
    with pytest.raises(SearchQueryError, match="Invalid search query"):
        search_fts(not_vault.db, query)


@pytest.mark.parametrize(("query", "expected"), [
    ("walrus NOT zebra", {"walrus-only"}),
    ("walrus AND NOT zebra", {"walrus-only"}),
    ("walrus AND - NOT zebra", {"walrus-only"}),
    ("walrus NOT -", {"both-words", "walrus-only"}),
])
def test_not_keeps_excluding(not_vault, query, expected):
    assert {r["id"] for r in search_fts(not_vault.db, query)} == expected


def test_not_with_no_operand_left_is_dropped():
    assert preprocess_query("walrus NOT - AND") == "walrus"
    assert preprocess_query("- NOT / OR -") == ""
