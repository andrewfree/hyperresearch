"""Error paths of the note, tag, topic and dedup commands under --json print
one JSON envelope on stdout.

They printed a Rich traceback and nothing on stdout instead: an invalid
--status or --type (pydantic ValidationError), a missing --body-file
(FileNotFoundError), and any of these commands run outside a vault
(VaultError). `--template nope` printed its fallback warning on stdout ahead
of the JSON, and dedup's no-vault envelope had no error_code or timestamp.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "v")])
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(tmp_path / "v")
    return tmp_path / "v"


def _error(args: list[str], code: str) -> dict:
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error_code"] == code
    assert envelope["timestamp"]
    return envelope


def _notes(root: Path) -> list[Path]:
    return list((root / "research" / "notes").glob("*.md"))


def test_invalid_status_and_type(root):
    envelope = _error(["note", "new", "X", "--status", "published", "--json"], "INVALID_STATUS")
    assert "evergreen" in envelope["error"]
    envelope = _error(["note", "new", "X", "--type", "bogus", "--json"], "INVALID_TYPE")
    assert "moc" in envelope["error"]
    assert _notes(root) == []


def test_missing_body_file(root, tmp_path):
    missing = tmp_path / "nonexistent.md"
    envelope = _error(["note", "new", "X", "--body-file", str(missing), "--json"], "FILE_NOT_FOUND")
    assert str(missing) in envelope["error"]
    assert _notes(root) == []


def test_unreadable_body_file(root, tmp_path):
    binary = tmp_path / "binary.md"
    binary.write_bytes(b"\xff\xfe\x00bad")
    _error(["note", "new", "X", "--body-file", str(binary), "--json"], "FILE_UNREADABLE")
    _error(["note", "new", "X", "--body-file", str(tmp_path), "--json"], "FILE_UNREADABLE")
    assert _notes(root) == []


def test_missing_template_warning_stays_inside_the_json(root):
    result = runner.invoke(app, ["note", "new", "Y", "--template", "nope", "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    assert "nope" in envelope["data"]["template_warning"]
    assert envelope["data"]["id"] == "y"


def test_missing_template_warning_in_human_mode(root):
    result = runner.invoke(app, ["note", "new", "Y", "--template", "nope"])
    assert result.exit_code == 0, result.output
    assert "Template 'nope' not found, using default." in result.output


@pytest.mark.parametrize(
    "args",
    [
        ["note", "list"],
        ["note", "show", "x"],
        ["note", "new", "z"],
        ["note", "update", "x", "--status", "review"],
        ["note", "rm", "x"],
        ["note", "mv", "x", "y"],
        ["tags"],
        ["tag", "list"],
        ["tag", "alias", "a", "b"],
        ["tag", "suggest"],
        ["topic", "list"],
        ["topic", "tree"],
        ["topic", "show", "t"],
        ["dedup"],
    ],
)
def test_outside_a_vault(args, tmp_path, monkeypatch):
    novault = tmp_path / "novault"
    novault.mkdir()
    monkeypatch.chdir(novault)
    envelope = _error([*args, "--json"], "NO_VAULT")
    assert "No hyperresearch vault found" in envelope["error"]


def test_note_edit_outside_a_vault_is_a_clean_error(tmp_path, monkeypatch):
    novault = tmp_path / "novault"
    novault.mkdir()
    monkeypatch.chdir(novault)
    result = runner.invoke(app, ["note", "edit", "x"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), result.exception
    assert "No hyperresearch vault found" in result.output
