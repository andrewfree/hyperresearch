import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

import pytest

from hyperresearch.core.hooks import _hook_command


def _hook_shell():
    if sys.platform != "win32":
        return shutil.which("sh") or shutil.which("bash") or "/bin/sh"

    roots = []
    git = shutil.which("git")
    if git:
        roots.extend(Path(git).parents)
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        directory = os.environ.get(variable)
        if directory:
            roots.append(Path(directory) / ("Programs/Git" if variable == "LOCALAPPDATA" else "Git"))
    for root in roots:
        for relative in ("bin/bash.exe", "usr/bin/sh.exe"):
            shell = root / relative
            parts = {part.casefold() for part in PureWindowsPath(str(shell)).parts}
            if not parts.intersection({"system32", "windowsapps"}) and shell.is_file():
                return str(shell)
    pytest.skip("Windows hook quoting needs a Git for Windows shell; none was found")


@pytest.mark.parametrize("folder", ["Q3 $budget", "Q3 `budget`", "Q3 $budget's files"])
def test_windows_hook_keeps_shell_metacharacters(tmp_path, folder):
    shell = _hook_shell()
    hook_path = tmp_path / folder / ".hyperresearch" / "hook.js"
    command = _hook_command(hook_path)
    assert shlex.split(command) == ["node", hook_path.as_posix()]
    # Git Bash uses POSIX shell quoting, including dollar expansion rules.
    result = subprocess.run([shell, "-c", "set -- " + command + '; printf "%s" "$2"'], capture_output=True, text=True, check=True)
    assert result.stdout == hook_path.as_posix()


@pytest.mark.parametrize("platform", ["linux", "darwin"])
def test_posix_hook_check_does_not_skip_without_shell_on_path(monkeypatch, platform):
    from types import SimpleNamespace

    monkeypatch.setitem(globals(), "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert _hook_shell() == "/bin/sh"


def test_windows_hook_check_skips_without_git_shell(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setitem(globals(), "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(shutil, "which", lambda name: r"C:\Windows\System32\bash.exe")
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(variable, str(tmp_path))
    with pytest.raises(pytest.skip.Exception, match="Git for Windows shell; none was found"):
        _hook_shell()


@pytest.mark.parametrize("relative_shell", ["bin/bash.exe", "usr/bin/sh.exe"])
def test_hook_shell_finds_git_outside_path(tmp_path, monkeypatch, relative_shell):
    from types import SimpleNamespace

    monkeypatch.setitem(globals(), "sys", SimpleNamespace(platform="win32"))
    git_root = tmp_path / "Program Files" / "Git"
    shell = git_root / relative_shell
    shell.parent.mkdir(parents=True)
    shell.touch()
    git = git_root / "cmd" / "git.exe"
    monkeypatch.setattr(shutil, "which", lambda name: str(git) if name == "git" else r"C:\Windows\System32\bash.exe")
    assert _hook_shell() == str(shell)


@pytest.mark.parametrize("launcher_directory", ["System32", "WindowsApps"])
def test_hook_shell_rejects_windows_launcher_directories(tmp_path, monkeypatch, launcher_directory):
    from types import SimpleNamespace

    monkeypatch.setitem(globals(), "sys", SimpleNamespace(platform="win32"))
    root = tmp_path / launcher_directory / "Git"
    shell = root / "bin" / "bash.exe"
    shell.parent.mkdir(parents=True)
    shell.touch()
    monkeypatch.setattr(shutil, "which", lambda name: str(root / "cmd" / "git.exe"))
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.setenv(variable, str(tmp_path))
    with pytest.raises(pytest.skip.Exception, match="Git for Windows shell; none was found"):
        _hook_shell()
