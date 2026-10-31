"""Existing caches must gain links without requiring source edits."""

import pytest

from hyperresearch.core.claims import ingest_claims_file
from hyperresearch.core.note import write_note
from hyperresearch.core.vault import Vault


@pytest.mark.parametrize("ref", ["ml", "equilibrium"])
def test_upgrade_restores_filtered_links_without_changing_notes(tmp_vault, ref):
    target = write_note(tmp_vault.notes_dir, ref, note_id=ref)
    source = write_note(tmp_vault.notes_dir, "Source", body=f"See [[{ref}]].")
    tmp_vault.auto_sync()
    claims = tmp_vault.research_dir / "claims-source.json"
    claims.write_text('[{"claim": "Keep this claim"}]')
    assert ingest_claims_file(tmp_vault.db, claims)["ingested"] == 1
    # Reproduce the cache left by the old filter, with unchanged Markdown.
    tmp_vault.db.execute("DELETE FROM links")
    tmp_vault.db.execute("UPDATE _meta SET value = '13' WHERE key = 'schema_version'")
    fingerprints = [tuple(row) for row in tmp_vault.db.execute(
        "SELECT id, file_mtime, content_hash FROM notes ORDER BY id"
    )]
    tmp_vault.db.commit()
    tmp_vault.close()
    original_bytes = {path: path.read_bytes() for path in (source, target)}

    with_vault = Vault(tmp_vault.root)
    with_vault.auto_sync()
    links = [tuple(row) for row in with_vault.db.execute(
        "SELECT target_ref, target_id FROM links WHERE source_id = 'source'"
    )]
    assert links == [(ref, ref)]
    assert with_vault.db.execute("SELECT claim FROM claims").fetchone()[0] == "Keep this claim"
    assert [tuple(row) for row in with_vault.db.execute(
        "SELECT id, file_mtime, content_hash FROM notes ORDER BY id"
    )] == fingerprints
    assert all(path.read_bytes() == content for path, content in original_bytes.items())
    with_vault.auto_sync()
    assert with_vault.db.execute("SELECT COUNT(*) FROM links").fetchone()[0] == 1
    with_vault.close()
