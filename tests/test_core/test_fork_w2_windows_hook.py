import shlex
import shutil
import subprocess

import pytest

from hyperresearch.core.hooks import _hook_command


@pytest.mark.parametrize("folder", ["Q3 $budget", "Q3 `budget`", "Q3 $budget's files"])
def test_windows_hook_keeps_shell_metacharacters(tmp_path, folder):
    shell = shutil.which("sh") or shutil.which("bash")
    if shell is None:
        pytest.skip("No POSIX shell on PATH; Git Bash is needed to check Windows hook quoting")
    hook_path = tmp_path / folder / ".hyperresearch" / "hook.js"
    command = _hook_command(hook_path)
    assert shlex.split(command) == ["node", hook_path.as_posix()]
    # Git Bash uses POSIX shell quoting, including dollar expansion rules.
    result = subprocess.run([shell, "-c", "set -- " + command + '; printf "%s" "$2"'], capture_output=True, text=True, check=True)
    assert result.stdout == hook_path.as_posix()
