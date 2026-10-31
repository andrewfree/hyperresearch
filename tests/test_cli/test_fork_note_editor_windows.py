"""On Windows an EDITOR quoted with single quotes still names its program.

Git for Windows writes editor commands like
`'C:/Program Files/Notepad++/notepad++.exe' -multiInst`, and shlex.quote
(what the other editor tests use to build EDITOR) quotes with single quotes
too. shlex.split(posix=False) keeps the quotes around a token, and only
double quotes were dropped, so the program name kept its single quotes and
could not be started. Windows is simulated through the editor's platform
helper, and the command is recorded instead of run.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from hyperresearch.cli.note import _open_in_editor


@pytest.fixture
def argv(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr("hyperresearch.cli.note._is_windows", lambda: True)
    monkeypatch.setattr(subprocess, "run", lambda args, *a, **k: calls.append(list(args)))
    monkeypatch.delenv("VISUAL", raising=False)
    return calls


@pytest.mark.parametrize(
    ("editor", "program"),
    [
        ("'C:/Program Files/Notepad++/notepad++.exe' -multiInst", "C:/Program Files/Notepad++/notepad++.exe"),
        ('"C:\\Program Files\\VS Code\\code.cmd" -multiInst', "C:\\Program Files\\VS Code\\code.cmd"),
        ("C:\\Users\\O'Brien\\ed.exe -multiInst", "C:\\Users\\O'Brien\\ed.exe"),
    ],
)
def test_quoted_program_is_unquoted(argv, monkeypatch, editor, program):
    monkeypatch.setenv("EDITOR", editor)
    _open_in_editor(Path("note.md"))
    assert argv == [[program, "-multiInst", "note.md"]]
