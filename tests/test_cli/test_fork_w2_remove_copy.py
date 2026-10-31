"""An unindexed copy must not inherit data belonging to a deleted note."""

import json

from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.claims import ingest_claims_file
from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync


def test_remove_drops_rows_before_sync_can_adopt_copy(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    original = write_note(tmp_vault.notes_dir, "Foo")
    tmp_vault.auto_sync()
    claims = tmp_vault.research_dir / "claims-foo.json"
    claims.write_text(json.dumps([{"claim": "Original claim"}]))
    assert ingest_claims_file(tmp_vault.db, claims)["ingested"] == 1
    tmp_vault.db.commit()
    copy = original.with_name("foo-copy.md")
    copy.write_bytes(original.read_bytes())
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert result.errors

    result = CliRunner().invoke(app, ["note", "rm", "foo", "--force", "--json"])
    assert result.exit_code == 0, result.output
    assert not original.exists()
    assert copy.exists()
    tmp_vault.auto_sync()
    row = tmp_vault.db.execute("SELECT path FROM notes WHERE id = 'foo'").fetchone()
    assert row["path"] == str(copy.relative_to(tmp_vault.root))
    assert tmp_vault.db.execute("SELECT COUNT(*) FROM claims").fetchone()[0] == 0
