"""`fetch --help` shows the wiki-link breadcrumb syntax it documents.

The CLI renders help text as Rich markup, so "[[note-id]]" lost its inner
"[note-id]" as a style tag and the help read "Suggested by []".
"""

from __future__ import annotations

from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def test_fetch_help_keeps_the_double_bracket_breadcrumbs():
    result = runner.invoke(app, ["fetch", "--help"], env={"COLUMNS": "400"})
    assert result.exit_code == 0, result.output
    assert "Prepends a 'Suggested by [[note-id]]' breadcrumb" in result.output
    assert "Appears next to the [[source-id]] breadcrumb." in result.output
