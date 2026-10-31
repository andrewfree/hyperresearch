"""`note edit` and `note new --edit` split $EDITOR like a shell command line.

`subprocess.run([editor, path])` took the whole value as a program name, so
an EDITOR with arguments (`code --wait`, `subl -w`) died with
"FileNotFoundError: No such file or directory: 'code --wait'". A program
that cannot be started is now a clean error, not a traceback.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()

RECORDER = "import json, sys\nwith open(sys.argv[1], 'a') as f:\n    f.write(json.dumps(sys.argv[2:]) + '\\n')\n"


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "v")])
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(tmp_path / "v")
    monkeypatch.delenv("VISUAL", raising=False)
    assert runner.invoke(app, ["note", "new", "Edit me"]).exit_code == 0
    return tmp_path / "v"


@pytest.fixture
def recorder(tmp_path: Path) -> tuple[str, Path]:
    """An editor command with arguments, and the log of what it was called with."""
    script = tmp_path / "recorder.py"
    script.write_text(RECORDER, encoding="utf-8")
    log = tmp_path / "calls.log"
    command = " ".join(shlex.quote(a) for a in (sys.executable, str(script), str(log)))
    return f"{command} --wait", log


def _calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def test_note_edit_passes_editor_arguments(root, recorder, monkeypatch):
    command, log = recorder
    monkeypatch.setenv("EDITOR", command)
    result = runner.invoke(app, ["note", "edit", "edit-me"])
    assert result.exit_code == 0, result.output
    [call] = _calls(log)
    assert call[0] == "--wait"
    assert Path(call[1]).resolve() == (root / "research" / "notes" / "edit-me.md").resolve()


def test_note_new_edit_passes_editor_arguments(root, recorder, monkeypatch):
    command, log = recorder
    monkeypatch.setenv("EDITOR", command)
    result = runner.invoke(app, ["note", "new", "Other", "--edit"])
    assert result.exit_code == 0, result.output
    [call] = _calls(log)
    assert call[0] == "--wait"
    assert Path(call[1]).name == "other.md"


def test_visual_is_used_when_editor_is_unset(root, recorder, monkeypatch):
    command, log = recorder
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.setenv("VISUAL", command)
    assert runner.invoke(app, ["note", "new", "Third", "--edit"]).exit_code == 0
    assert Path(_calls(log)[0][1]).name == "third.md"


@pytest.mark.skipif(os.name == "nt", reason="uses a shebang script")
def test_unquoted_program_path_with_spaces_still_works(root, tmp_path, monkeypatch):
    folder = tmp_path / "my editors"
    folder.mkdir()
    log = tmp_path / "spaced.log"
    program = folder / "ed"
    program.write_text(
        f"#!{sys.executable}\nimport sys\nopen({str(log)!r}, 'w').write(sys.argv[1])\n",
        encoding="utf-8",
    )
    program.chmod(0o755)
    monkeypatch.setenv("EDITOR", str(program))
    result = runner.invoke(app, ["note", "edit", "edit-me"])
    assert result.exit_code == 0, result.output
    assert log.read_text(encoding="utf-8").endswith("edit-me.md")


@pytest.mark.parametrize("command", ["no-such-editor-xyz --wait", "'unclosed"])
def test_editor_that_cannot_start_is_a_clean_error(root, monkeypatch, command):
    monkeypatch.setenv("EDITOR", command)
    result = runner.invoke(app, ["note", "edit", "edit-me"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), result.exception
    assert "EDITOR" in result.output


def test_note_new_json_edit_failure_keeps_stdout_json(root, monkeypatch):
    monkeypatch.setenv("EDITOR", "no-such-editor-xyz --wait")
    result = runner.invoke(app, ["note", "new", "Json", "--edit", "--json"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), result.exception
    assert json.loads(result.stdout)["data"]["id"] == "json"
    assert "no-such-editor-xyz" in result.stderr
