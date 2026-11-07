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


@pytest.mark.parametrize("newline", ["\r\n", "\n"])
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


@pytest.mark.parametrize("newline", ["\r\n", "\r", "\n"])
def test_legacy_cached_body_has_one_clean_heading(tmp_vault, monkeypatch, newline):
    from hyperresearch.serve.server import HyperresearchHandler

    path = tmp_vault.notes_dir / "headed.md"
    content = "---\nid: headed\ntitle: Headed\n---\n\n" + BODY
    path.write_bytes(content.encode("utf-8"))
    tmp_vault.auto_sync()
    # An unchanged note can retain a body cached before newline normalization.
    tmp_vault.db.execute(
        "UPDATE note_content SET body = ? WHERE note_id = 'headed'",
        (BODY.replace("\n", newline),),
    )
    handler = HyperresearchHandler.__new__(HyperresearchHandler)
    handler._db = tmp_vault.db
    handler.vault = tmp_vault
    sent = []
    monkeypatch.setattr(handler, "_send", lambda *args: sent.append(args))
    handler._serve_note("headed")
    assert sent[0][0] == 200
    _, page, title = sent[0]
    assert title == "Headed"
    assert page.count("<h1>") == 1
    assert "<h1>Headed Differently</h1>" in page
    assert "\r" not in page


def test_lone_cr_notes_are_not_indexed(tmp_vault):
    path = tmp_vault.notes_dir / "classic.md"
    path.write_bytes(b"---\rid: classic\rtitle: Classic\r---\rBody\r")
    tmp_vault.auto_sync()
    assert tmp_vault.db.execute("SELECT id FROM notes WHERE id = 'classic'").fetchone() is None
