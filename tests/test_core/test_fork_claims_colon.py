"""Colon-bearing terms stay phrases in claims searches."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.claims import search_claims
from hyperresearch.core.note import write_note
from hyperresearch.search.fts import search_fts


@pytest.fixture
def colon_vault(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, "Source", body="the a:b ratio is 3")
    tmp_vault.auto_sync()
    path = tmp_vault.research_dir / "claims-source.json"
    path.write_text(json.dumps([
        {"claim": "the a:b ratio is 3"},
        {"claim": "the ab ratio is 4"},
        {"claim": "a scattered b ratio is 5"},
    ]), encoding="utf-8")
    result = CliRunner().invoke(app, ["claims", "ingest", str(path), "--json"])
    assert result.exit_code == 0, repr(result.exception)
    assert json.loads(result.output)["data"]["ingested"] == 3
    return tmp_vault


@pytest.mark.parametrize("query", ["a:b", '"a:b"', "a:b AND ratio", "ratio a:b"])
def test_colon_term_matches_a_phrase(colon_vault, query):
    rows = search_claims(colon_vault.db, query)
    assert [r["claim"] for r in rows] == ["the a:b ratio is 3"]
    assert [r["id"] for r in search_fts(colon_vault.db, query)] == ["source"]


def test_claims_cli_finds_bare_colon_term(colon_vault):
    result = CliRunner().invoke(app, ["claims", "search", "a:b", "--json"])
    assert result.exit_code == 0, repr(result.exception)
    rows = json.loads(result.output)["data"]["claims"]
    assert [r["claim"] for r in rows] == ["the a:b ratio is 3"]
