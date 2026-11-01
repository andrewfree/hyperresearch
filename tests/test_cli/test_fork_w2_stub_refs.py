"""Stubs resolve the original reference and repeated runs are idempotent."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import read_note, write_note

runner = CliRunner()


@pytest.mark.parametrize("command", ["graph", "repair"])
def test_stub_preserves_ref_title_and_actual_id(tmp_vault, monkeypatch, command):
    monkeypatch.chdir(tmp_vault.root)
    write_note(tmp_vault.notes_dir, "Occupied", note_id="gpt-4-technical-report", body="Taken id.")
    write_note(tmp_vault.notes_dir, "Source", body=(
        "[[GPT-4 Technical Report]] [[Mixed Case-Ref]] [[delta#section-two]] "
        "[[delta#another]] [[mixed case-ref]]"
    ))
    args = ["graph", "stub", "-j"] if command == "graph" else [
        "repair", "--no-enrich", "--no-promote", "--no-index", "--no-docs", "-j"
    ]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    files = sorted(tmp_vault.temp_dir.glob("*.md"))
    notes = [read_note(p, tmp_vault.root) for p in files]
    assert len(notes) == 3
    assert {n.meta.title.lower() for n in notes} == {
        "gpt-4 technical report", "mixed case-ref", "delta"
    }
    if command == "graph":
        rows = json.loads(result.output)["data"]["stubbed"]
        assert {r["id"] for r in rows} == {n.meta.id for n in notes}
        assert "gpt-4-technical-report-2" in {r["id"] for r in rows}
    broken = runner.invoke(app, ["graph", "broken", "-j"])
    assert json.loads(broken.output)["data"] == []
    for _ in range(2):
        again = runner.invoke(app, args)
        assert again.exit_code == 0, again.output
        data = json.loads(again.output)["data"]
        assert (data["count"] if command == "graph" else data["stubs"]) == 0
        assert sorted(tmp_vault.temp_dir.glob("*.md")) == files
