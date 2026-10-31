"""Operator-mode queries drop operators left without an operand, and glued
alphanumeric terms match their spaced form only as an adjacent phrase.

A term that reduces to nothing ('-', '/', '"-"') was dropped but its operator
was kept, so 'attention AND -' was an FTS5 syntax error and 'attention AND
"-"' matched nothing. Operator mode never expanded 'mamba3' to also find
'Mamba 3'. The plain-mode spaced form was a scattered AND of prefix terms, so
'llama3.1' matched any note holding llama, 3 and 1 anywhere.
"""

from __future__ import annotations

import pytest

from hyperresearch.search.fts import SearchQueryError, preprocess_query, search_fts


@pytest.fixture
def term_vault(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    notes = {
        "Attention Notes": "attention mechanisms. AI and ML overview. mamba3 and h264 in python3.",
        "Llama Scatter": "llama: version 3 of something, then 1 more",
        "Mamba Spaced": "Mamba 3 supports h264.",
        "Model Roundup": "GPT-4o and Llama 3.1 release.",
    }
    for title, body in notes.items():
        write_note(tmp_vault.notes_dir, title, body=body)
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    return tmp_vault


def _ids(vault, query):
    return {r["id"] for r in search_fts(vault.db, query)}


# --- Operators left without an operand ----------------------------------------


@pytest.mark.parametrize(("query", "expected"), [
    ("attention AND -", "attention"),
    ("- AND attention", "attention"),
    ("attention AND - AND", "attention"),
    ('attention AND "-"', "attention"),
    ("AI AND / OR ML", "AI OR ML"),
    ("attention AND NOT mamba", "attention NOT mamba"),
    ("(- OR /) AND attention", "attention"),
    ("NEAR(- /) AND attention", "attention"),
])
def test_operator_without_operand_is_dropped(query, expected):
    assert preprocess_query(query) == expected


@pytest.mark.parametrize("query", [
    "attention AND -",
    "AI AND / OR ML",
    'attention AND "-"',
    "(- OR /) AND attention",
])
def test_dangling_operator_query_still_matches(term_vault, query):
    assert "attention-notes" in _ids(term_vault, query)


def test_operator_query_of_only_tokenless_terms_has_no_searchable_terms(term_vault):
    with pytest.raises(SearchQueryError, match="no searchable terms"):
        search_fts(term_vault.db, "- AND /")


@pytest.mark.parametrize("query", ["covid AND (vaccines", "attention AND )", "attention AND ("])
def test_unbalanced_parentheses_are_still_rejected(term_vault, query):
    with pytest.raises(SearchQueryError, match="Invalid search query"):
        search_fts(term_vault.db, query)


# --- Glued alphanumeric terms -------------------------------------------------


def test_glued_term_expands_in_operator_mode(term_vault):
    assert _ids(term_vault, "mamba3 AND h264") == {"attention-notes", "mamba-spaced"}
    assert _ids(term_vault, "mamba3 OR nevermatches") == {"attention-notes", "mamba-spaced"}


def test_glued_group_next_to_another_term_is_valid(term_vault):
    # FTS5 has no implicit AND next to a parenthesized group.
    assert _ids(term_vault, "h264 mamba3 OR nevermatches") == {"attention-notes", "mamba-spaced"}
    assert preprocess_query("x NOT foo mamba3") == 'x NOT ( foo AND (mamba3 OR "mamba 3") )'


def test_glued_term_inside_near_is_a_plain_phrase(term_vault):
    assert preprocess_query("NEAR(mamba3 h264)") == "NEAR ( mamba3 h264 )"
    assert "attention-notes" in _ids(term_vault, "NEAR(mamba3 h264)")


@pytest.mark.parametrize("query", ["llama3.1", "llama3.1 AND release"])
def test_spaced_form_needs_adjacent_parts(term_vault, query):
    ids = _ids(term_vault, query)
    assert "model-roundup" in ids
    assert "llama-scatter" not in ids


def test_spaced_form_keeps_a_digit_letter_suffix_glued(term_vault):
    # 'GPT-4o' is indexed as gpt, 4o, so the spaced form of gpt4o is 'gpt 4o'.
    assert "model-roundup" in _ids(term_vault, "gpt4o")


def test_plain_mode_spaced_form_is_one_phrase():
    assert preprocess_query("mamba3") == '("mamba3"* OR "mamba 3"*)'
    assert preprocess_query("w1") == '("w1"* OR "w 1"*)'
