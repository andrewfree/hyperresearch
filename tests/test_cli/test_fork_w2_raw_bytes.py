"""Raw notes preserve bytes across line endings and output encodings."""

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app


@pytest.mark.parametrize("newline", [b"\r\n", b"\r", b"\n"])
def test_raw_preserves_file_bytes(tmp_vault, monkeypatch, newline):
    monkeypatch.chdir(tmp_vault.root)
    path = tmp_vault.notes_dir / "raw.md"
    header = b"---\nid: raw\ntitle: Raw\n---\n\n"
    body = "Café: [bold]你好[/bold]\nlast line".encode()
    # Lone CRs remain content; frontmatter needs LF or CRLF delimiters.
    header_newline = b"\r\n" if newline == b"\r\n" else b"\n"
    content = header.replace(b"\n", header_newline) + body.replace(b"\n", newline)
    path.write_bytes(content)

    result = CliRunner().invoke(app, ["note", "show", "raw", "--raw"])

    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == content
