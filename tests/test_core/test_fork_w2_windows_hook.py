import shlex
import shutil
import subprocess
import sys

import pytest

from hyperresearch.core.hooks import _hook_command


@pytest.mark.parametrize("folder", ["Q3 $budget", "Q3 `budget`", "Q3 $budget's files"])
def test_windows_hook_keeps_shell_metacharacters(tmp_path, folder):
    shell = shutil.which("sh") or shutil.which("bash")
    if shell is None:
        if sys.platform == "win32":
            pytest.skip("Windows needs Git Bash on PATH to check hook quoting")
        shell = "/bin/sh"
    hook_path = tmp_path / folder / ".hyperresearch" / "hook.js"
    command = _hook_command(hook_path)
    assert shlex.split(command) == ["node", hook_path.as_posix()]
    # Git Bash uses POSIX shell quoting, including dollar expansion rules.
    result = subprocess.run([shell, "-c", "set -- " + command + '; printf "%s" "$2"'], capture_output=True, text=True, check=True)
    assert result.stdout == hook_path.as_posix()


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_posix_hook_check_does_not_skip_without_shell_on_path(tmp_path, monkeypatch, platform):
    from types import SimpleNamespace

    # Replace only this test module's platform seam, not interpreter globals.
    monkeypatch.setitem(globals(), "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        hook_path = tmp_path / "Q3 $budget" / ".hyperresearch" / "hook.js"
        return SimpleNamespace(stdout=hook_path.as_posix())

    monkeypatch.setattr(subprocess, "run", run)
    try:
        test_windows_hook_keeps_shell_metacharacters(tmp_path, "Q3 $budget")
    except pytest.skip.Exception as exc:
        pytest.fail(f"POSIX shell coverage must not skip: {exc}")
    assert calls[0][0] == "/bin/sh"


def test_windows_hook_check_skips_only_when_no_posix_shell_is_available(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setitem(globals(), "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(pytest.skip.Exception, match="Windows needs Git Bash on PATH"):
        test_windows_hook_keeps_shell_metacharacters(tmp_path, "Q3 $budget")
