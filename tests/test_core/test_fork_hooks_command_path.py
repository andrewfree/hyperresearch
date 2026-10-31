"""The PreToolUse hook command must reach hook.js from where the project is now.

Two ways it did not:

- The command holds an absolute path. After the project moved (or a teammate
  cloned a committed settings.json), re-install found an entry mentioning
  hyperresearch, returned early, and kept the old path, so node failed with
  "Cannot find module" on every WebSearch/WebFetch call.
- The path was put in double quotes, inside which the shell still expands `$`
  and backticks, so a directory like `Q3 $budget` lost part of its name.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys

import pytest

from hyperresearch.core.hooks import _install_claude_hook

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell semantics")


def _commands(root) -> list[str]:
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    return [
        h["command"]
        for entry in settings["hooks"]["PreToolUse"]
        for h in entry["hooks"]
    ]


def _argv_through_sh(command: str, tmp_path) -> list[str]:
    """Run `command` through sh with a fake `node` that prints its arguments."""
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "node"
    fake.write_text('#!/bin/sh\nfor a in "$@"; do printf "%s\\n" "$a"; done\n', encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}"}
    env.pop("budget", None)
    proc = subprocess.run(
        ["sh", "-c", command], capture_output=True, text=True, env=env, timeout=30
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.splitlines()


def test_reinstall_after_a_move_points_the_hook_at_the_new_path(tmp_path):
    old = tmp_path / "old"
    old.mkdir()
    assert _install_claude_hook(old, "hyperresearch") is not None
    new = tmp_path / "new"
    old.rename(new)

    result = _install_claude_hook(new, "hyperresearch")

    assert result is not None and "updated" in result
    [command] = _commands(new)
    assert (new / ".hyperresearch" / "hook.js").as_posix() in command
    assert "/old/" not in command
    # Settled: a second run changes nothing.
    assert _install_claude_hook(new, "hyperresearch") is None


def test_refresh_keeps_foreign_hooks_and_the_entry_position(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    stale = {
        "matcher": "WebSearch|WebFetch",
        "hooks": [{"type": "command", "command": 'node "/gone/.hyperresearch/hook.js"'}],
    }
    foreign = {"matcher": "Bash", "hooks": [{"type": "command", "command": "hyperresearch lint"}]}
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"model": "opus", "hooks": {"PreToolUse": [stale, foreign]}}), encoding="utf-8"
    )

    _install_claude_hook(root, "hyperresearch")

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["model"] == "opus"
    pre = settings["hooks"]["PreToolUse"]
    assert len(pre) == 2
    assert (root / ".hyperresearch" / "hook.js").as_posix() in pre[0]["hooks"][0]["command"]
    assert pre[1] == foreign


def test_an_up_to_date_entry_from_an_earlier_install_is_left_as_written(tmp_path):
    # Earlier installs double-quoted every path. One that is still correct
    # must not be rewritten (settings.json is often committed).
    root = tmp_path / "my project"
    root.mkdir()
    command = f'node "{(root / ".hyperresearch" / "hook.js").as_posix()}"'
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"hooks": {"PreToolUse": [
            {"matcher": "WebSearch|WebFetch", "hooks": [{"type": "command", "command": command}]}
        ]}}, indent=2) + "\n",
        encoding="utf-8",
    )
    before = path.read_bytes()

    assert _install_claude_hook(root, "hyperresearch") is None
    assert path.read_bytes() == before


@posix_only
@pytest.mark.parametrize("dirname", ["Q3 $budget", "a`echo x`b", 'say "hi"', "back\\slash"])
def test_hook_command_survives_the_shell(tmp_path, dirname):
    root = tmp_path / dirname
    root.mkdir()

    _install_claude_hook(root, "hyperresearch")

    [command] = _commands(root)
    assert _argv_through_sh(command, tmp_path) == [(root / ".hyperresearch" / "hook.js").as_posix()]


@posix_only
@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_hook_runs_from_a_dollar_path(tmp_path):
    root = tmp_path / "Q3 $budget"
    (root / ".hyperresearch").mkdir(parents=True)

    _install_claude_hook(root, "hyperresearch")

    [command] = _commands(root)
    proc = subprocess.run(
        ["sh", "-c", command],
        input="{}",
        capture_output=True,
        text=True,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    assert "HYPERRESEARCH" in json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
