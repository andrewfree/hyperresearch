"""Reading authoritative markdown must not depend on a healthy cache."""

import pytest

from hyperresearch.core.note import read_note, write_note


@pytest.mark.parametrize("cache", [b"broken cache", b"", None])
def test_read_note_tolerates_missing_or_unusable_cache(tmp_vault, cache):
    path = write_note(tmp_vault.notes_dir, "Source", body="See [[iv]] and [[real-note]].")
    tmp_vault.close()
    tmp_vault.db_path.unlink()
    if cache is not None:
        tmp_vault.db_path.write_bytes(cache)
    note = read_note(path, tmp_vault.root)
    assert note.meta.title == "Source"
    assert note.body == "See [[iv]] and [[real-note]]."
    assert note.outgoing_links == ["real-note"]
    if cache is None:
        assert not tmp_vault.db_path.exists()
    else:
        assert tmp_vault.db_path.read_bytes() == cache
