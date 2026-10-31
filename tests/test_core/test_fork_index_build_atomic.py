"""`index build` keeps the previous pages when a rebuild fails.

build_all deleted every research/index/*.md first and then wrote each page as
it was built, so a failure partway (one page's query raising) left the vault
with only the pages built before it. Pages are now all rendered first, and
only then written, with stale pages removed.
"""

from __future__ import annotations

import stat

import pytest

from hyperresearch.indexgen.generator import IndexGenerator


@pytest.fixture
def indexed_vault(seeded_vault):
    IndexGenerator(seeded_vault).build_all()
    return seeded_vault


def _pages(vault) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in vault.index_dir.iterdir()}


def test_failed_rebuild_keeps_every_previous_page(indexed_vault, monkeypatch):
    before = _pages(indexed_vault)
    assert {"_index.md", "_recent.md", "_orphans.md", "_most-linked.md"} <= set(before)

    def boom(self):
        raise RuntimeError("mid-build failure")

    monkeypatch.setattr(IndexGenerator, "_build_recent", boom)
    with pytest.raises(RuntimeError, match="mid-build failure"):
        IndexGenerator(indexed_vault).build_all()
    assert _pages(indexed_vault) == before


def test_rebuild_replaces_pages_and_removes_stale_ones(indexed_vault):
    stale = indexed_vault.index_dir / "_tag-gone.md"
    stale.write_text("---\ntitle: Tag: gone\ntype: index\n---\n", encoding="utf-8")
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    write_note(indexed_vault.notes_dir, "Fresh Note", body="New.")
    execute_sync(indexed_vault, compute_sync_plan(indexed_vault))

    built = IndexGenerator(indexed_vault).build_all()
    names = set(_pages(indexed_vault))
    assert names == {b.removeprefix("index/") for b in built}
    assert "_tag-gone.md" not in names
    assert "[[fresh-note]]" in (indexed_vault.index_dir / "_index.md").read_text(encoding="utf-8")
    # Written through a temp file, the page keeps the mode a plain write gives.
    reference = indexed_vault.root / "reference.txt"
    reference.write_text("x", encoding="utf-8")
    mode = stat.S_IMODE((indexed_vault.index_dir / "_index.md").stat().st_mode)
    assert mode == stat.S_IMODE(reference.stat().st_mode)


def test_single_page_build_still_writes_its_file(seeded_vault):
    IndexGenerator(seeded_vault)._build_stats()
    assert (seeded_vault.index_dir / "_stats.md").exists()
    assert {p.name for p in seeded_vault.index_dir.iterdir()} == {"_stats.md"}
