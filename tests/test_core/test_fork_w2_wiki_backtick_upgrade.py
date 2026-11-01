"""Unchanged vaults regain backtick wiki links on cache upgrade."""

from hyperresearch.core.claims import ingest_claims_file
from hyperresearch.core.note import write_note
from hyperresearch.core.vault import Vault


def test_upgrade_replaces_mangled_backtick_links(tmp_vault):
    target = write_note(tmp_vault.notes_dir, "A `code` title", note_id="target")
    source = write_note(tmp_vault.notes_dir, "Source", body="See [[A `code` title]].")
    tmp_vault.auto_sync()
    claims = tmp_vault.research_dir / "claims-source.json"
    claims.write_text('[{"claim": "Keep this claim"}]')
    assert ingest_claims_file(tmp_vault.db, claims)["ingested"] == 1
    # Reproduce the previous cache without editing the authoritative notes.
    tmp_vault.db.execute("DELETE FROM links")
    tmp_vault.db.execute(
        "INSERT INTO links (source_id, target_ref, line_number) VALUES ('source', 'A   title', 1)"
    )
    tmp_vault.db.execute("UPDATE _meta SET value = '15' WHERE key = 'schema_version'")
    fingerprints = [tuple(row) for row in tmp_vault.db.execute(
        "SELECT id, file_mtime, content_hash FROM notes ORDER BY id"
    )]
    tmp_vault.db.commit()
    tmp_vault.close()
    original_bytes = {path: path.read_bytes() for path in (source, target)}

    vault = Vault(tmp_vault.root)
    vault.auto_sync()
    links = [tuple(row) for row in vault.db.execute(
        "SELECT target_ref, target_id FROM links WHERE source_id = 'source'"
    )]
    assert links == [("A `code` title", "target")]
    assert vault.db.execute("SELECT claim FROM claims").fetchone()[0] == "Keep this claim"
    assert [tuple(row) for row in vault.db.execute(
        "SELECT id, file_mtime, content_hash FROM notes ORDER BY id"
    )] == fingerprints
    assert all(path.read_bytes() == content for path, content in original_bytes.items())
    vault.auto_sync()
    assert vault.db.execute("SELECT COUNT(*) FROM links").fetchone()[0] == 1
    vault.close()
