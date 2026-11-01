"""Creation dates of notes without a frontmatter timestamp stay stable."""

import os
from datetime import UTC, datetime

from hyperresearch.core.sync import compute_sync_plan, execute_sync


def test_missing_created_uses_file_time_and_survives_sync(tmp_vault):
    note_path = tmp_vault.notes_dir / "hand.md"
    original = "---\ntitle: Handwritten\n---\nfirst\n"
    note_path.write_text(original)
    timestamp = 1_700_000_000
    os.utime(note_path, (timestamp, timestamp))

    def sync_created(force=False):
        result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=force))
        assert not result.errors
        return tmp_vault.db.execute("SELECT created FROM notes WHERE id = 'hand'").fetchone()[0]

    created = sync_created()
    assert datetime.fromisoformat(created) == datetime.fromtimestamp(timestamp, UTC)
    note_path.write_text(original + "second\n")
    os.utime(note_path, (timestamp + 10, timestamp + 10))
    assert sync_created() == created
    assert sync_created(force=True) == created
    assert note_path.read_text() == original + "second\n"


def test_declared_created_overrides_cache_and_survives_removal(tmp_vault):
    note_path = tmp_vault.notes_dir / "hand.md"
    for declared in ("2020-01-01", "2021-01-01", None):
        created_line = f"created: {declared}\n" if declared else ""
        note_path.write_text(f"---\ntitle: Handwritten\n{created_line}---\nbody\n")
        result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
        assert not result.errors
        created = tmp_vault.db.execute("SELECT created FROM notes WHERE id = 'hand'").fetchone()[0]
        assert created.startswith(declared or "2021-01-01")
