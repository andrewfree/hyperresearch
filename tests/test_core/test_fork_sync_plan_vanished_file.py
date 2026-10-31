"""A file removed between the scan and its hash read is a delete, not a crash.

compute_sync_plan lists the research tree, stats each file, and later reads
the bytes of every indexed file whose mtime moved to compare content hashes.
The stat had a FileNotFoundError guard, the hash read did not: a file that
vanished in between (a fetch that lost a race cleans up its note, an editor
replacing a file) crashed the whole sync with a traceback.
"""

from __future__ import annotations

import os
from pathlib import Path

from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync


def test_compute_sync_plan_treats_a_file_removed_before_its_hash_read_as_a_delete(
    tmp_vault, monkeypatch
):
    keeper = write_note(tmp_vault.notes_dir, "Keeper", body="stays")
    gone = write_note(tmp_vault.notes_dir, "Gone", body="removed mid-scan")
    assert execute_sync(tmp_vault, compute_sync_plan(tmp_vault)).errors == []
    # Move both mtimes, so the plan reads both files to compare their hashes.
    for path in (keeper, gone):
        st = path.stat()
        os.utime(path, (st.st_atime, st.st_mtime + 5))

    real_read_bytes = Path.read_bytes

    def remove_then_read(self: Path) -> bytes:
        if self == gone:
            self.unlink()
        return real_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", remove_then_read)
    plan = compute_sync_plan(tmp_vault)
    monkeypatch.undo()

    gone_rel = gone.relative_to(tmp_vault.root).as_posix()
    assert plan.to_delete == [gone_rel]
    assert plan.to_add == [] and plan.to_update == []
    # The keeper's bytes did not change: only its mtime moved.
    assert plan.unchanged == 1

    result = execute_sync(tmp_vault, plan)
    assert result.errors == [] and result.deleted == 1
    ids = [r["id"] for r in tmp_vault.db.execute("SELECT id FROM notes")]
    assert ids == [keeper.stem]
