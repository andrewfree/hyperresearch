"""Raw notes preserve bytes across line endings and output encodings."""

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.note import write_note


@pytest.mark.parametrize("newline", [b"\r\n", b"\r", b"\n"])
def test_raw_preserves_file_bytes(tmp_vault, monkeypatch, newline):
    monkeypatch.chdir(tmp_vault.root)
    path = write_note(tmp_vault.notes_dir, "Raw", body="Café: [bold]你好[/bold]\nlast line")
    header, body = path.read_bytes().split(b"\n---\n", 1)
    content = header + b"\n---\n" + body.rstrip(b"\n").replace(b"\n", newline)
    path.write_bytes(content)

    result = CliRunner().invoke(app, ["note", "show", "raw", "--raw"])

    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == content
