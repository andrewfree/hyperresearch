"""`assets list` shows each asset's type label and its text literally.

The line was built as f"  [{type}] ...", which Rich parsed as a style tag
and dropped, so the output read "   page: .../screenshot.png" with no
[screenshot] or [image]. Alt text and filenames from fetched pages were
parsed as markup the same way.
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def test_assets_list_keeps_the_type_label_and_bracketed_text(tmp_path: Path):
    assert runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Assets"]).exit_code == 0
    root = tmp_path / "kb"
    os.chdir(root)
    made = runner.invoke(app, ["note", "new", "Page", "--body", "x", "--json"])
    note_id = json.loads(made.stdout)["data"]["id"]

    conn = sqlite3.connect(root / ".hyperresearch" / "hyperresearch.db")
    try:
        conn.executemany(
            "INSERT INTO assets (note_id, type, filename, alt_text, content_type, size_bytes, created_at) "
            "VALUES (?, ?, ?, ?, 'image/png', 2048, ?)",
            [
                (note_id, "screenshot", "shot.png", "Page screenshot", "2026-01-01T00:00:00"),
                (note_id, "image", "fig[b].png", "Figure [/b] two", "2026-01-02T00:00:00"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(app, ["assets", "list"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    assert f"[image] {note_id}: fig[b].png (2KB) — Figure [/b] two" in result.output
    assert f"[screenshot] {note_id}: shot.png (2KB) — Page screenshot" in result.output

    # `assets path` output is read back as a file path, so a bracket Rich
    # swallowed would point at a file that does not exist.
    path = runner.invoke(app, ["assets", "path", note_id, "--type", "image"])
    assert path.exit_code == 0, path.output
    assert path.output.strip() == "fig[b].png"
