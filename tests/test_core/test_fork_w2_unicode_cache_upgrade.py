"""Unicode resolution also upgrades existing, unchanged vault caches."""

import pytest

from hyperresearch.core.note import write_note
from hyperresearch.core.vault import Vault


@pytest.mark.parametrize("kind", ["id", "alias", "title"])
def test_existing_cache_resolves_unicode_without_markdown_edits(tmp_vault, kind):
    kwargs = {"note_id": "straße" if kind == "id" else "target"}
    if kind == "alias":
        kwargs["extra_frontmatter"] = {"aliases": ["Straße"]}
    target = write_note(tmp_vault.notes_dir, "Straße" if kind == "title" else "Target", **kwargs)
    source = write_note(tmp_vault.notes_dir, "Source", body="See [[STRASSE]].")
    tmp_vault.auto_sync()
    # Version 14 used SQLite LOWER, leaving these links unresolved.
    tmp_vault.db.execute("UPDATE links SET target_id = NULL")
    tmp_vault.db.execute("UPDATE _meta SET value = '14' WHERE key = 'schema_version'")
    tmp_vault.db.commit()
    fingerprints = [tuple(row) for row in tmp_vault.db.execute(
        "SELECT id, file_mtime, content_hash FROM notes ORDER BY id"
    )]
    original_bytes = {path: path.read_bytes() for path in (source, target)}
    tmp_vault.close()

    vault = Vault(tmp_vault.root)
    try:
        for _ in range(2):
            vault.auto_sync()
            assert vault.db.execute("SELECT target_id FROM links").fetchone()[0] == kwargs["note_id"]
        assert [tuple(row) for row in vault.db.execute(
            "SELECT id, file_mtime, content_hash FROM notes ORDER BY id"
        )] == fingerprints
        assert all(path.read_bytes() == content for path, content in original_bytes.items())
    finally:
        vault.close()
