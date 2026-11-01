"""Wiki references keep backticks through extraction, sync and viewing."""

import pytest

from hyperresearch.core.note import read_note, write_note
from hyperresearch.core.patterns import mask_code, strip_code
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.serve.server import HyperresearchHandler


@pytest.mark.parametrize("ref", ["A `code` title", "算法 ``code`` 标题", "A `unfinished title"])
def test_backtick_reference_resolves_in_viewer(tmp_vault, ref):
    write_note(tmp_vault.notes_dir, ref, note_id="target")
    write_note(tmp_vault.notes_dir, "Source", body=f"* [[{ref}]]\n")
    source = tmp_vault.notes_dir / "source.md"
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    assert not result.errors
    assert read_note(source, tmp_vault.root).outgoing_links == [ref]
    link = tmp_vault.db.execute(
        "SELECT target_ref, target_id FROM links WHERE source_id = 'source'"
    ).fetchone()
    assert tuple(link) == (ref, "target")
    handler = object.__new__(HyperresearchHandler)
    handler.vault = tmp_vault
    handler._db = tmp_vault.db
    responses = []
    handler._send = lambda *args: responses.append(args)
    handler._serve_note("source")
    assert 'href="/note/target"' in responses[0][1]


@pytest.mark.parametrize("strip", [strip_code, mask_code])
def test_wiki_backticks_do_not_pair_with_surrounding_code(strip):
    ref = "[[A `unfinished title]]"
    text = f"{ref} and `[[hidden]]`\n```\n[[hidden `too`]]\n```"
    cleaned = strip(text)
    assert ref in cleaned
    assert "hidden" not in cleaned
    assert cleaned.count("\n") == text.count("\n")
