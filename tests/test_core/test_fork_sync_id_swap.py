"""Id edits that trade ids with each other apply in one pass.

Since #159 a file whose `id:` changes is renamed in place, and the rename
frees the old id for a later file in the pass. The collision check ran
before any rename, though: when `aaa.md` now declares `bbb` and `bbb.md`
declares `aaa`, each saw its new id still held by the other's row and was
refused, on every sync, sync --force and repair, while `note show` served
the stale bodies and later edits to either file were never indexed. A chain
of id edits (`a` to `b`, `b` to `c`) failed the same way when the scan
listed it in the wrong order. An id edit now waits for the edit that frees
its id, and edits that trade ids in a ring step aside to parking ids and
then take their new ones, all or none.
"""

from __future__ import annotations

import os
import sqlite3

import pytest

from hyperresearch.core.sync import compute_sync_plan, execute_sync

NOW = "2026-09-15T00:00:00"


def _note(path, note_id: str, title: str, body: str, extra: str = "") -> None:
    rewrite = path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nid: {note_id}\ntitle: {title}\n{extra}---\n\n{body}\n", encoding="utf-8")
    if rewrite:
        # A rewrite within one filesystem timestamp tick keeps the old mtime,
        # and the sync plan skips a file whose mtime did not move.
        st = path.stat()
        os.utime(path, (st.st_atime, st.st_mtime + 5))


def _rows(vault) -> dict[str, str]:
    return {r["id"]: r["path"] for r in vault.db.execute("SELECT id, path FROM notes")}


def _seed(vault, note_id: str) -> None:
    vault.db.execute(
        "INSERT INTO claims (note_id, claim, claim_hash, ingested_at) VALUES (?, ?, ?, ?)",
        (note_id, f"{note_id} claim", f"h-{note_id}", NOW),
    )
    vault.db.execute(
        "INSERT INTO sources (url, note_id, domain, fetched_at, provider) VALUES (?, ?, 'ex.org', ?, 'builtin')",
        (f"https://ex.org/{note_id}", note_id, NOW),
    )
    vault.db.commit()


def _claims(vault) -> dict[str, str]:
    return dict(vault.db.execute("SELECT claim, note_id FROM claims").fetchall())


def _sources(vault) -> dict[str, str]:
    return dict(vault.db.execute("SELECT url, note_id FROM sources").fetchall())


def _body(vault, note_id: str) -> str:
    return vault.db.execute("SELECT body FROM note_content WHERE note_id = ?", (note_id,)).fetchone()["body"]


def _sync(vault, force: bool = False):
    return execute_sync(vault, compute_sync_plan(vault, force=force))


@pytest.mark.parametrize("force", [False, True], ids=["sync", "sync-force"])
def test_sync_applies_a_swap_of_two_notes_ids_in_one_pass(tmp_vault, force):
    """Each row is renamed in place to the id its file now declares, and
    its claim and sources row go with it, as for a single id edit. The
    edit made with the swap is indexed."""
    notes = tmp_vault.notes_dir
    _note(notes / "aaa.md", "aaa", "Aaa", "body A")
    _note(notes / "bbb.md", "bbb", "Bbb", "body B")
    _note(notes / "other.md", "other", "Other", "Links [[aaa]] and [[bbb]].")
    assert _sync(tmp_vault).errors == []
    _seed(tmp_vault, "aaa")
    _seed(tmp_vault, "bbb")

    _note(notes / "aaa.md", "bbb", "Aaa", "body A\nNEW CONTENT")
    _note(notes / "bbb.md", "aaa", "Bbb", "body B")
    result = _sync(tmp_vault, force)

    assert result.errors == []
    # --force re-indexes the untouched other.md too.
    assert result.updated == (3 if force else 2) and result.added == result.deleted == 0
    assert _rows(tmp_vault) == {
        "bbb": "research/notes/aaa.md",
        "aaa": "research/notes/bbb.md",
        "other": "research/notes/other.md",
    }
    assert _claims(tmp_vault) == {"aaa claim": "bbb", "bbb claim": "aaa"}
    assert _sources(tmp_vault) == {"https://ex.org/aaa": "bbb", "https://ex.org/bbb": "aaa"}
    assert "NEW CONTENT" in _body(tmp_vault, "bbb")
    assert "body B" in _body(tmp_vault, "aaa")
    db = tmp_vault.db
    hits = db.execute("SELECT id FROM notes_fts WHERE notes_fts MATCH 'new'").fetchall()
    assert [r["id"] for r in hits] == ["bbb"]
    assert sorted(r["id"] for r in db.execute("SELECT id FROM notes_fts")) == ["aaa", "bbb", "other"]
    links = {r["target_ref"]: r["target_id"] for r in db.execute("SELECT target_ref, target_id FROM links")}
    assert links == {"aaa": "aaa", "bbb": "bbb"}
    assert not any(":" in note_id for note_id in _rows(tmp_vault))
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []

    plan = compute_sync_plan(tmp_vault)
    assert plan.to_add == [] and plan.to_update == [] and plan.to_delete == []


def test_sync_applies_a_ring_of_three_id_edits_in_one_pass(tmp_vault):
    notes = tmp_vault.notes_dir
    for name in ("a", "b", "c"):
        _note(notes / f"{name}.md", name, name.upper(), f"body {name}")
    assert _sync(tmp_vault).errors == []
    for name in ("a", "b", "c"):
        _seed(tmp_vault, name)

    _note(notes / "a.md", "b", "A", "body a")
    _note(notes / "b.md", "c", "B", "body b")
    _note(notes / "c.md", "a", "C", "body c")
    result = _sync(tmp_vault)

    assert result.errors == [] and result.updated == 3
    assert _rows(tmp_vault) == {
        "b": "research/notes/a.md",
        "c": "research/notes/b.md",
        "a": "research/notes/c.md",
    }
    assert _claims(tmp_vault) == {"a claim": "b", "b claim": "c", "c claim": "a"}
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("edit_first", ["a.md", "b.md"])
def test_sync_applies_a_chain_of_id_edits_whatever_the_scan_order(tmp_vault, edit_first):
    """`a.md` renames to `b` while `b.md` renames to `c`, which nothing
    holds. Listed with `a.md` first, the rename to `b` waits until `b.md`
    has freed it, rather than being refused until the next run."""
    notes = tmp_vault.notes_dir
    _note(notes / "a.md", "a", "A", "body a")
    _note(notes / "b.md", "b", "B", "body b")
    assert _sync(tmp_vault).errors == []
    _seed(tmp_vault, "a")
    _seed(tmp_vault, "b")

    _note(notes / "a.md", "b", "A", "body a")
    _note(notes / "b.md", "c", "B", "body b")
    plan = compute_sync_plan(tmp_vault)
    # The scan order is the filesystem's. Fix it, both ways round.
    plan.to_update.sort(key=lambda p: p.name != edit_first)
    result = execute_sync(tmp_vault, plan)

    assert result.errors == [] and result.updated == 2
    assert _rows(tmp_vault) == {"b": "research/notes/a.md", "c": "research/notes/b.md"}
    assert _claims(tmp_vault) == {"a claim": "b", "b claim": "c"}


def test_sync_refuses_an_id_edit_onto_an_id_whose_rename_fails(tmp_vault):
    """`b.md`, whose row `a.md` waits on, fails its upsert (a duplicate
    alias): it keeps `b`, so the rename of `a.md` to `b` is the ordinary
    collision it was before."""
    notes = tmp_vault.notes_dir
    _note(notes / "a.md", "a", "A", "body a")
    _note(notes / "b.md", "b", "B", "body b")
    assert _sync(tmp_vault).errors == []

    _note(notes / "a.md", "b", "A", "body a")
    _note(notes / "b.md", "c", "B", "body b", "aliases: [dup, dup]\n")
    plan = compute_sync_plan(tmp_vault)
    plan.to_update.sort(key=lambda p: p.name)
    result = execute_sync(tmp_vault, plan)

    errors = {os.path.basename(e["path"]): e["error"] for e in result.errors}
    assert set(errors) == {"a.md", "b.md"}
    assert "aliases" in errors["b.md"]
    assert "id collision: 'b' already belongs to 'research/notes/b.md'" in errors["a.md"]
    assert _rows(tmp_vault) == {"a": "research/notes/a.md", "b": "research/notes/b.md"}


def test_sync_undoes_the_whole_swap_when_one_side_fails(tmp_vault):
    """`bbb.md` carries a duplicate alias that the aliases primary key
    refuses inside its upsert. Neither rename sticks: both rows keep their
    ids, claims and sources rows, both files are reported, and the pass
    commits the rest."""
    notes = tmp_vault.notes_dir
    _note(notes / "aaa.md", "aaa", "Aaa", "body A")
    _note(notes / "bbb.md", "bbb", "Bbb", "body B")
    assert _sync(tmp_vault).errors == []
    _seed(tmp_vault, "aaa")
    _seed(tmp_vault, "bbb")

    _note(notes / "aaa.md", "bbb", "Aaa", "body A")
    _note(notes / "bbb.md", "aaa", "Bbb", "body B", "aliases: [dup, dup]\n")
    _note(notes / "fresh.md", "fresh", "Fresh", "fresh body")
    raised = result = None
    try:
        result = _sync(tmp_vault)
    except sqlite3.Error as exc:
        raised = exc
    assert raised is None, f"the pass raised: {raised}"

    errors = {os.path.basename(e["path"]): e["error"] for e in result.errors}
    assert set(errors) == {"aaa.md", "bbb.md"}
    assert "aliases" in errors["bbb.md"]
    assert "research/notes/bbb.md" in errors["aaa.md"] and "run sync again" in errors["aaa.md"]
    assert (result.added, result.updated) == (1, 0)
    assert not tmp_vault.db.in_transaction
    assert _rows(tmp_vault) == {
        "aaa": "research/notes/aaa.md",
        "bbb": "research/notes/bbb.md",
        "fresh": "research/notes/fresh.md",
    }
    assert _claims(tmp_vault) == {"aaa claim": "aaa", "bbb claim": "bbb"}
    assert _sources(tmp_vault) == {"https://ex.org/aaa": "aaa", "https://ex.org/bbb": "bbb"}
    assert "body A" in _body(tmp_vault, "aaa") and "body B" in _body(tmp_vault, "bbb")
    assert sorted(r["id"] for r in tmp_vault.db.execute("SELECT id FROM notes_fts")) == [
        "aaa", "bbb", "fresh",
    ]
    assert tmp_vault.db.execute("PRAGMA foreign_key_check").fetchall() == []
