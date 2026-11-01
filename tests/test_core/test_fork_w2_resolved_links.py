"""Real note references take precedence over citation heuristics."""

import pytest

from hyperresearch.core.note import read_note, write_note
from hyperresearch.core.patterns import is_valid_wiki_link_target
from hyperresearch.core.sync import compute_sync_plan, execute_sync

WORDS = ["equilibrium", "algorithms", "plate-tectonics", "figma", "table-tennis"]
AMBIGUOUS = ["ml", "dl", "cv", "mix", "fig-3", "100", "Note 1", "IV"]


@pytest.mark.parametrize("ref", WORDS)
def test_document_prefix_words_are_valid(ref):
    assert is_valid_wiki_link_target(ref)


@pytest.mark.parametrize("order", ["hub_first", "targets_first", "targets_later"])
def test_existing_ids_titles_aliases_override_heuristics(tmp_vault, order):
    refs = WORDS + AMBIGUOUS
    body = " ".join(f"[[{ref}]]" for ref in refs) + " [[xii]] [[figure-99]] [[missing-topic]]"
    if order != "targets_first":
        write_note(tmp_vault.notes_dir, "Hub", body=body)
    if order == "targets_later":
        tmp_vault.auto_sync()
    for ref in WORDS + AMBIGUOUS[:6]:
        write_note(tmp_vault.notes_dir, ref, note_id=ref)
    write_note(tmp_vault.notes_dir, "Note 1", note_id="titled-note")
    write_note(tmp_vault.notes_dir, "Alias target", note_id="alias-target", extra_frontmatter={"aliases": ["IV"]})
    if order == "targets_first":
        write_note(tmp_vault.notes_dir, "Hub", body=body)
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert not result.errors
    links = {r["target_ref"]: r["target_id"] for r in tmp_vault.db.execute(
        "SELECT target_ref, target_id FROM links WHERE source_id = 'hub'"
    )}
    assert set(links) == set(refs) | {"missing-topic"}
    assert links["Note 1"] == "titled-note"
    assert links["IV"] == "alias-target"
    assert all(links[ref] == ref for ref in WORDS + AMBIGUOUS[:6])
    assert links["missing-topic"] is None

    note = read_note(tmp_vault.notes_dir / "hub.md", tmp_vault.root)
    assert set(note.outgoing_links) == set(refs) | {"missing-topic"}
