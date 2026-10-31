"""Link locations depend on delimiters, not metadata validation."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note

runner = CliRunner()


@pytest.mark.parametrize("invalid", ["status: invalid", "tags: [unfinished"])
def test_cached_links_keep_file_lines_when_metadata_is_invalid(tmp_vault, monkeypatch, invalid):
    path = write_note(tmp_vault.notes_dir, "Source", body="Paragraph\n\nSee [[missing-paper]].\n")
    tmp_vault.auto_sync()
    content = path.read_text().replace("status: draft", invalid)
    path.write_text(content)
    line = next(i for i, text in enumerate(content.splitlines(), 1) if "missing-paper" in text)
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["graph", "broken", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"][0]["line_number"] == line
    result = runner.invoke(app, ["lint", "-r", "broken-links"])
    assert result.exit_code == 0, result.output
    assert f"research/notes/source.md line {line}" in " ".join(result.output.split())
