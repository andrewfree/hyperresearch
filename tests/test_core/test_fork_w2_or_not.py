"""Unsupported OR NOT must not silently become a narrower NOT query."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.search.fts import SearchQueryError, preprocess_query, search_fts


@pytest.mark.parametrize("query", [
    "a OR NOT b",
    "a OR\nNOT b",
    "a AND (b OR NOT c)",
    "a OR - NOT b",
])
def test_or_not_is_rejected(tmp_vault, query):
    with pytest.raises(SearchQueryError, match="OR NOT"):
        search_fts(tmp_vault.db, query)


def test_cli_or_not_reports_bad_query(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)

    result = CliRunner().invoke(app, ["search", "a OR NOT b", "--json"])

    assert result.exit_code == 2, result.output
    response = json.loads(result.stdout)
    assert response["error_code"] == "BAD_QUERY"
    assert "OR NOT" in response["error"]


def test_quoted_or_not_and_supported_operators_are_preserved():
    assert preprocess_query('a OR "NOT b"') == 'a OR "NOT b"'
    assert preprocess_query('"a OR NOT b"') == '"a OR NOT b"'
    assert preprocess_query("a AND NOT b") == "a NOT b"
    assert preprocess_query("a NOT b") == "a NOT b"
