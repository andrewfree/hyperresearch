"""Link diagnostics point to lines in the markdown file."""

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note

runner = CliRunner()


@pytest.mark.parametrize("newline,bom", [("\n", ""), ("\r\n", "\ufeff")])
def test_link_diagnostics_use_file_lines(tmp_vault, monkeypatch, newline, bom):
    path = write_note(
        tmp_vault.notes_dir, "Source",
        body="para one\n\npara two\n\nSee [[missing-paper]] and [[target]].\n",
    )
    write_note(tmp_vault.notes_dir, "Target")
    content = path.read_text()
    path.write_bytes((bom + content.replace("\n", newline)).encode())
    line = next(i for i, text in enumerate(content.splitlines(), 1) if "missing-paper" in text)
    monkeypatch.chdir(tmp_vault.root)

    for args in (["graph", "broken"], ["graph", "outlinks", "source"],
                 ["graph", "backlinks", "target"]):
        result = runner.invoke(app, [*args, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)["data"]
        if isinstance(data, dict):
            data = data.get("outlinks", data.get("backlinks"))
        assert data
        assert all(link["line_number"] == line for link in data)
    result = runner.invoke(app, ["graph", "broken"])
    assert f"source line {line}: [[missing-paper]]" in result.output
    result = runner.invoke(app, ["lint", "-r", "broken-links"])
    assert f"research/notes/source.md line {line}" in " ".join(result.output.split())
