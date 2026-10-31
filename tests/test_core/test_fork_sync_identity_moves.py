"""A row follows the file that still declares its id, wherever the paths go.

Sync matched a moved file to its row only when the row's old path was gone
from disk. When the old path holds a file again in the same pass, sync went
by path: it renamed the row at that path in place to whatever id the new
file there declares, and the moved file, which still declares the old id
with the bytes the row was indexed from, got a fresh row. So reusing a path
(`mv paper.md moved.md` and a new `paper.md`) handed the paper's claims and
sources row to the unrelated new note, and a rotation (`mv b.md c.md; mv
a.md b.md`) deleted `a` with its claims and refused `c.md` as a collision
with the stale row at `b.md` on every sync. A rename keeps the file's mtime,
so when the two notes were written in the same millisecond the plan did not
even see that `b.md` changed.

A row now moves to a changed file that declares its id with its indexed
bytes whenever the row's own file no longer declares that id, and the path
it leaves is a new file.
"""

from __future__ import annotations

import os

import pytest

from hyperresearch.core.sync import compute_sync_plan, execute_sync

NOW = "2026-09-15T00:00:00"
T0 = 1_700_000_000.0


def _note(path, note_id: str, title: str, body: str, mtime: float | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {note_id}\ntitle: {title}\n---\n\n{body}\n", encoding="utf-8")
    if mtime is not None:
        os.utime(path, (mtime, mtime))


def _sync(vault):
    return execute_sync(vault, compute_sync_plan(vault))


def _rows(vault) -> dict[str, str]:
    return {r["id"]: r["path"] for r in vault.db.execute("SELECT id, path FROM notes")}


def _seed(vault, note_id: str) -> None:
    """A claim and the fetch dedup row: rows a markdown file cannot rebuild."""
    vault.db.execute(
        "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES (?, ?, ?, ?)",
        (note_id, f"{note_id} claim", f"h-{note_id}", NOW),
    )
    vault.db.execute(
        "INSERT INTO sources (url, note_id, domain, fetched_at, provider) VALUES (?, ?, 'ex.org', ?, 'builtin')",
        (f"https://ex.org/{note_id}", note_id, NOW),
    )
    vault.db.commit()


def _claims(vault) -> dict[str, str | None]:
    return dict(vault.db.execute("SELECT claim, note_id FROM claims").fetchall())


def _sources(vault) -> dict[str, str | None]:
    return dict(vault.db.execute("SELECT url, note_id FROM sources").fetchall())


def _body(vault, note_id: str) -> str:
    return vault.db.execute("SELECT body FROM note_content WHERE note_id = ?", (note_id,)).fetchone()["body"]


def _assert_settled(vault) -> None:
    assert vault.db.execute("PRAGMA foreign_key_check").fetchall() == []
    plan = compute_sync_plan(vault)
    assert plan.to_add == [] and plan.to_update == [] and plan.to_delete == []


def test_sync_keeps_a_moved_notes_rows_when_a_new_file_reuses_its_path(tmp_vault):
    """`paper.md` moves to `moved.md` and a new, unrelated `paper.md` takes
    its place. The paper's claim and sources row stay with the paper at its
    new path; the new file is a note of its own."""
    notes = tmp_vault.notes_dir
    _note(notes / "paper.md", "paper", "Paper", "The paper body.", T0)
    assert _sync(tmp_vault).errors == []
    _seed(tmp_vault, "paper")

    os.rename(notes / "paper.md", notes / "moved.md")
    _note(notes / "paper.md", "replacement", "Replacement", "A new file.", T0 + 10)
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (1, 1, 0)
    assert _rows(tmp_vault) == {
        "paper": "research/notes/moved.md",
        "replacement": "research/notes/paper.md",
    }
    assert _claims(tmp_vault) == {"paper claim": "paper"}
    assert _sources(tmp_vault) == {"https://ex.org/paper": "paper"}
    assert "The paper body" in _body(tmp_vault, "paper")
    assert "A new file" in _body(tmp_vault, "replacement")
    _assert_settled(tmp_vault)


@pytest.mark.parametrize("same_mtime", [False, True], ids=["mtimes-apart", "same-mtime"])
def test_sync_follows_a_rotation_of_note_files(tmp_vault, same_mtime):
    """`mv b.md c.md; mv a.md b.md`: each note's row, claim and sources row
    follow its file. With both files written in the same instant the plan
    sees no mtime change at `b.md`, which now holds `a`."""
    notes = tmp_vault.notes_dir
    _note(notes / "a.md", "a", "A", "aaa", T0)
    _note(notes / "b.md", "b", "B", "bbb", T0 if same_mtime else T0 + 10)
    assert _sync(tmp_vault).errors == []
    _seed(tmp_vault, "a")
    _seed(tmp_vault, "b")

    os.rename(notes / "b.md", notes / "c.md")
    os.rename(notes / "a.md", notes / "b.md")
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (0, 2, 0)
    assert _rows(tmp_vault) == {"a": "research/notes/b.md", "b": "research/notes/c.md"}
    assert _claims(tmp_vault) == {"a claim": "a", "b claim": "b"}
    assert _sources(tmp_vault) == {"https://ex.org/a": "a", "https://ex.org/b": "b"}
    assert "aaa" in _body(tmp_vault, "a") and "bbb" in _body(tmp_vault, "b")
    _assert_settled(tmp_vault)


def test_sync_follows_two_note_files_that_swap_paths(tmp_vault):
    """`a.md` and `b.md` trade places through a temp name. Each path now
    holds the other note: the rows trade paths, not ids, so the claims
    stay with the text they were extracted from."""
    notes = tmp_vault.notes_dir
    _note(notes / "a.md", "a", "A", "aaa", T0)
    _note(notes / "b.md", "b", "B", "bbb", T0 + 10)
    assert _sync(tmp_vault).errors == []
    _seed(tmp_vault, "a")
    _seed(tmp_vault, "b")

    os.rename(notes / "a.md", notes / "swap.tmp")
    os.rename(notes / "b.md", notes / "a.md")
    os.rename(notes / "swap.tmp", notes / "b.md")
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (0, 2, 0)
    assert _rows(tmp_vault) == {"a": "research/notes/b.md", "b": "research/notes/a.md"}
    assert _claims(tmp_vault) == {"a claim": "a", "b claim": "b"}
    assert "aaa" in _body(tmp_vault, "a") and "bbb" in _body(tmp_vault, "b")
    _assert_settled(tmp_vault)


def test_sync_deletes_the_note_whose_file_a_move_overwrote(tmp_vault):
    """`mv a.md b.md` replaces `b`'s file with `a`'s. `a` keeps its row
    and claim at its new path; nothing declares `b` any more, so `b` is
    deleted as a removed note is: its claim goes and its sources row keeps
    the URL with no note."""
    notes = tmp_vault.notes_dir
    _note(notes / "a.md", "a", "A", "aaa", T0)
    _note(notes / "b.md", "b", "B", "bbb", T0 + 10)
    assert _sync(tmp_vault).errors == []
    _seed(tmp_vault, "a")
    _seed(tmp_vault, "b")

    os.rename(notes / "a.md", notes / "b.md")
    result = _sync(tmp_vault)

    assert result.errors == []
    assert (result.added, result.updated, result.deleted) == (0, 1, 1)
    assert _rows(tmp_vault) == {"a": "research/notes/b.md"}
    assert _claims(tmp_vault) == {"a claim": "a"}
    assert _sources(tmp_vault) == {"https://ex.org/a": "a", "https://ex.org/b": None}
    _assert_settled(tmp_vault)
