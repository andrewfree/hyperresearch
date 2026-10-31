"""Claims queries use the same safe FTS syntax as note searches."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.claims import ingest_claims_file, search_claims
from hyperresearch.core.note import write_note


@pytest.fixture
def claims_vault(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, "Source")
    tmp_vault.auto_sync()
    path = tmp_vault.research_dir / "claims-source.json"
    path.write_text(json.dumps([{"claim": "GPT-4 measured 86.4% and it's reliable."}]))
    assert ingest_claims_file(tmp_vault.db, path)["ingested"] == 1
    tmp_vault.db.commit()
    return tmp_vault


@pytest.mark.parametrize("query", ["GPT-4", "86.4%", "it's", "a:b", "GPT-4 AND reliable"])
def test_claims_punctuation_queries(claims_vault, query):
    rows = search_claims(claims_vault.db, query)
    if query != "a:b":
        assert [r["note_id"] for r in rows] == ["source"]
    result = CliRunner().invoke(app, ["claims", "search", query, "--json"])
    assert result.exit_code == 0, repr(result.exception)
    assert json.loads(result.output)["data"]["claims"] == rows


@pytest.mark.parametrize("query", ["***", "NEAR(foo", "foo AND (bar"])
def test_invalid_claims_queries_return_json_error(claims_vault, query):
    result = CliRunner().invoke(app, ["claims", "search", query, "--json"])
    assert result.exit_code != 0
    assert json.loads(result.output)["ok"] is False
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_claims_database_error_returns_json(claims_vault, monkeypatch):
    from hyperresearch.cli import claims_cmd

    monkeypatch.setattr(claims_cmd, "_vault_or_exit", lambda _: claims_vault)
    claims_vault.db.execute("DROP TABLE claims_fts")
    result = CliRunner().invoke(app, ["claims", "search", "source", "--json"])
    assert result.exit_code != 0
    assert json.loads(result.output)["ok"] is False
