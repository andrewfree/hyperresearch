"""Status boosts and the --ranked quality factor apply before LIMIT/OFFSET.

SQL ordered and paged by raw bm25, then the evergreen/deprecated/stale
multipliers (and --ranked quality) re-sorted only the fetched page. So
--limit 1 returned a penalized deprecated note ahead of a boosted evergreen
one, and --offset 1 returned the top result of the full ranking.
"""

from __future__ import annotations

import pytest

from hyperresearch.search.fts import search_fts

RANKING = {"boost_evergreen": 1.5, "penalize_deprecated": 0.3, "penalize_stale": 0.7}


@pytest.fixture
def rank_vault(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    write_note(
        tmp_vault.notes_dir, "Quantum Error Correction", status="deprecated",
        body="Quantum error correction quantum error correction surface codes.",
    )
    write_note(
        tmp_vault.notes_dir, "Surface Codes Overview", status="evergreen",
        body=(
            "An overview of quantum error correction with surface codes and "
            "decoders and many other words here to dilute."
        ),
    )
    for i in range(8):
        write_note(tmp_vault.notes_dir, f"Filler {i}", body=f"Gardening soil {i}.")
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    return tmp_vault


def _page(vault, **kw):
    return [(r["id"], round(r["score"], 6)) for r in search_fts(vault.db, "quantum error", **kw)]


def test_full_ranking_puts_boosted_note_first(rank_vault):
    ids = [i for i, _ in _page(rank_vault, ranking=RANKING)]
    assert ids == ["surface-codes-overview", "quantum-error-correction"]


@pytest.mark.parametrize("quality_ranked", [False, True])
def test_pages_are_slices_of_the_full_ranking(rank_vault, quality_ranked):
    full = _page(rank_vault, ranking=RANKING, quality_ranked=quality_ranked)
    assert len(full) == 2
    for offset in range(len(full)):
        page = _page(
            rank_vault, ranking=RANKING, quality_ranked=quality_ranked, limit=1, offset=offset
        )
        assert page == full[offset:offset + 1]


def test_quality_factor_reorders_before_paging(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    # Same status, so only the quality factor can flip the raw bm25 order.
    write_note(tmp_vault.notes_dir, "Alpha Notes", body="decoders decoders decoders.")
    write_note(tmp_vault.notes_dir, "Beta Notes", body="decoders and a few more words.")
    for i in range(8):  # so the term is rare enough for a nonzero bm25 idf
        write_note(tmp_vault.notes_dir, f"Filler {i}", body=f"Gardening soil {i}.")
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    db = tmp_vault.db
    raw = [r["id"] for r in search_fts(db, "decoders")]
    assert raw == ["alpha-notes", "beta-notes"]
    db.execute("UPDATE notes SET quality_score = 0.0 WHERE id = 'alpha-notes'")
    db.execute("UPDATE notes SET quality_score = 1.0 WHERE id = 'beta-notes'")
    db.commit()

    def page(**kw):
        return [(r["id"], round(r["score"], 6)) for r in search_fts(db, "decoders", **kw)]

    full = page(quality_ranked=True)
    assert [i for i, _ in full] == ["beta-notes", "alpha-notes"]
    assert page(quality_ranked=True, limit=1) == full[:1]
    assert page(quality_ranked=True, limit=1, offset=1) == full[1:2]


def test_without_ranking_scores_are_raw_bm25(rank_vault):
    # No ranking dict: no status multipliers, so the dense deprecated note wins.
    ids = [i for i, _ in _page(rank_vault)]
    assert ids == ["quantum-error-correction", "surface-codes-overview"]
    assert _page(rank_vault, limit=1, offset=1) == _page(rank_vault)[1:2]
