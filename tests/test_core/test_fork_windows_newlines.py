"""Windows note bytes have the same parsed meaning as LF note bytes."""

import hashlib

import pytest

from hyperresearch.core.enrich import auto_summary
from hyperresearch.core.frontmatter import parse_frontmatter
from hyperresearch.core.note import read_note
from hyperresearch.serve.renderer import render_markdown

BODY = "# Headed Differently\n\nA useful summary about [[target]].\n\n```text\n[[hidden]]\n```\n"


@pytest.mark.parametrize("newline", ["\r\n", "\r", "\n"])
def test_renderer_normalizes_note_newlines(newline):
    rendered = render_markdown(BODY.replace("\n", newline))
    assert rendered == render_markdown(BODY)
    assert "<h1>Headed Differently</h1>" in rendered
    assert "\r" not in rendered


@pytest.mark.parametrize("newline", ["\r\n", "\r", "\n"])
def test_note_bytes_parse_and_sync_with_normalized_newlines(tmp_vault, newline):
    text = "---\nid: headed\ntitle: Headed\nsummary: Stored summary\n---\n\n" + BODY
    content = text.replace("\n", newline).encode("utf-8")
    path = tmp_vault.notes_dir / "headed.md"
    path.write_bytes(content)

    note = read_note(path, tmp_vault.root)
    assert note.meta.title == "Headed"
    assert note.meta.summary == "Stored summary"
    assert note.body == BODY
    assert note.content_hash == hashlib.sha256(content).hexdigest()
    assert note.outgoing_links == ["target"]
    assert auto_summary(note.body) == auto_summary(BODY)
    assert parse_frontmatter(text.replace("\n", "\r\n"))[0].title == "Headed"

    tmp_vault.auto_sync()
    row = tmp_vault.db.execute("SELECT body FROM note_content WHERE note_id = 'headed'").fetchone()
    assert row["body"] == BODY
    links = tmp_vault.db.execute("SELECT target_ref, line_number FROM links WHERE source_id = 'headed'").fetchall()
    assert [(r["target_ref"], r["line_number"]) for r in links] == [("target", 3)]
    assert path.read_bytes() == content
