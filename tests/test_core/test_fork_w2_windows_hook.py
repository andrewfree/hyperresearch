import shlex
import subprocess
import sys

import pytest

from hyperresearch.core.hooks import _hook_command


@pytest.mark.parametrize("folder", ["Q3 $budget", "Q3 `budget`", "Q3 $budget's files"])
def test_windows_hook_keeps_shell_metacharacters(tmp_path, monkeypatch, folder):
    hook_path = tmp_path / folder / ".hyperresearch" / "hook.js"
    monkeypatch.setattr(sys, "platform", "win32")
    command = _hook_command(hook_path)
    assert shlex.split(command) == ["node", hook_path.as_posix()]
    # Git Bash uses POSIX shell quoting, including dollar expansion rules.
    result = subprocess.run(["/bin/sh", "-c", "set -- " + command + '; printf "%s" "$2"'], capture_output=True, text=True, check=True)
    assert result.stdout == hook_path.as_posix()
