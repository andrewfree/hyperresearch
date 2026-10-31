"""A metadata-only rewrite must leave the note body's bytes alone.

FRONTMATTER_RE ended in `\\n---\\s*\\n?`: the `\\s*` after the closing
delimiter ran on past the blank separator line into the first body line and
ate its leading spaces. `note update`, MCP `update_note`, batch and repair all
write `serialize_frontmatter(meta) + "\\n" + body` back, so adding a tag moved
the first line of an indented code block out of the block for good. The
closing delimiter now takes its own line ending and the one blank line
render_note writes after it, nothing more.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.frontmatter import parse_frontmatter, render_note, serialize_frontmatter
from hyperresearch.models.note import NoteMeta

runner = CliRunner()

BODIES = [
    "    indented code line\n    second line\n\nText.\n",
    "\tTabbed first line\n",
    "\n\nTwo blank lines before the text.\n",
    "# Heading\n\nPlain text.\n",
    "",
]


@pytest.mark.parametrize("body", BODIES)
def test_parse_returns_the_body_render_note_wrote(body):
    meta = NoteMeta(title="T", id="t", tags=["a"])
    content = render_note(meta, body)
    parsed, parsed_body = parse_frontmatter(content)
    assert parsed_body == body
    # The rewrite every metadata-only edit does is byte-identical.
    assert serialize_frontmatter(parsed) + "\n" + parsed_body == content


def test_standard_layouts_still_give_the_same_body():
    for content in (
        "---\ntitle: T\n---\n\nBody\n",
        "---\ntitle: T\n---\nBody\n",
        "---\r\ntitle: T\r\n---\r\n\r\nBody\r\n",
        "---  \ntitle: T\n---  \n\nBody\n",
    ):
        meta, body = parse_frontmatter(content)
        assert meta.title == "T", content
        assert body.rstrip("\r\n") == "Body", content
    meta, body = parse_frontmatter("---\ntitle: T\n---")
    assert meta.title == "T"
    assert body == ""


def test_indent_on_a_first_line_with_no_separator_is_kept():
    _, body = parse_frontmatter("---\ntitle: T\n---\n    code\n")
    assert body == "    code\n"


def test_note_update_keeps_the_first_body_line_indented(tmp_path: Path, monkeypatch):
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    monkeypatch.chdir(root)
    body_file = tmp_path / "indent.md"
    body = "    indented code line\n    second line\n\nText.\n"
    body_file.write_text(body, encoding="utf-8")
    result = runner.invoke(app, ["note", "new", "Indent", "--body-file", str(body_file), "--json"])
    assert result.exit_code == 0, result.output
    path = root / "research" / "notes" / "indent.md"
    assert path.read_text(encoding="utf-8").endswith("\n\n" + body)

    result = runner.invoke(app, ["note", "update", "indent", "--add-tag", "t", "--json"])
    assert result.exit_code == 0, result.output
    text = path.read_text(encoding="utf-8")
    assert "tags:\n- t\n" in text
    assert text.endswith("---\n\n" + body)


def test_mcp_update_note_keeps_the_first_body_line_indented(tmp_path: Path, monkeypatch):
    mcp = pytest.importorskip("hyperresearch.mcp.server")
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    monkeypatch.chdir(root)
    body = "    indented code line\n    second line\n\nText.\n"
    body_file = tmp_path / "indent.md"
    body_file.write_text(body, encoding="utf-8")
    assert runner.invoke(app, ["note", "new", "Indent", "--body-file", str(body_file)]).exit_code == 0
    monkeypatch.setattr(mcp, "_vault", None)
    try:
        assert '"ok": true' in mcp.update_note("indent", add_tags="t")
    finally:
        mcp._vault = None
    text = (root / "research" / "notes" / "indent.md").read_text(encoding="utf-8")
    assert text.endswith("---\n\n" + body)
