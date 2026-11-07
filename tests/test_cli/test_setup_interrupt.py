"""Non-interactive setup lets install finish interrupting its browser tree."""

import os
import signal
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app


@pytest.mark.parametrize("cleanup_timeout", [False, True])
@pytest.mark.parametrize("args", [[], ["--json"]])
def test_setup_waits_for_interrupted_install_then_exits_130(monkeypatch, tmp_path, args, cleanup_timeout):
    process = Mock()
    process.wait.side_effect = [
        KeyboardInterrupt,
        subprocess.TimeoutExpired("install", 10) if cleanup_timeout else 130,
        -9,
    ]
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(subprocess, "call", Mock(side_effect=KeyboardInterrupt))
    result = CliRunner().invoke(app, ["setup", str(tmp_path), *args], input="")
    assert result.exit_code == 130
    assert process.wait.call_count == (3 if cleanup_timeout else 2)
    assert process.wait.call_args_list[1].kwargs == {"timeout": 10}
    assert process.kill.call_count == int(cleanup_timeout)


@pytest.mark.parametrize("args", [[], ["--json"]])
def test_setup_ctrl_c_allows_real_installer_tree_cleanup(tmp_path, args):
    if sys.platform == "win32":
        pytest.skip("POSIX process group interrupt; Windows uses the wait seam")
    import fcntl

    lock_file = tmp_path / "grandchild.lock"
    ready_file = tmp_path / "ready"
    installer_pid_file = tmp_path / "installer.pid"
    installer = tmp_path / "installer.py"
    grandchild = (
        "import fcntl, pathlib, sys, time; "
        "lock = open(sys.argv[1], 'w'); "
        "fcntl.flock(lock, fcntl.LOCK_EX); "
        "pathlib.Path(sys.argv[2]).touch(); time.sleep(60)"
    )
    installer.write_text(
        "import os, pathlib, subprocess, sys, time\n"
        f"pathlib.Path({str(installer_pid_file)!r}).write_text(str(os.getpid()))\n"
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}, {str(lock_file)!r}, {str(ready_file)!r}])\n"
        "time.sleep(60)\n", encoding="utf-8",
    )
    install_child = tmp_path / "install_child.py"
    install_child.write_text(
        "import sys, time\n"
        "from hyperresearch.cli import _browser\n"
        "killpg = _browser.os.killpg\n"
        "def slow_cleanup(pid, sig):\n"
        "    time.sleep(0.6)\n"
        "    killpg(pid, sig)\n"
        "_browser.os.killpg = slow_cleanup\n"
        "try:\n"
        f"    _browser.run_installer([sys.executable, {str(installer)!r}])\n"
        "except KeyboardInterrupt:\n"
        "    sys.exit(130)\n", encoding="utf-8",
    )
    launcher = tmp_path / "setup_launcher.py"
    launcher.write_text(
        "import subprocess, sys\n"
        "from hyperresearch.cli import app\n"
        "popen = subprocess.Popen\n"
        "def delegate(cmd, **kwargs):\n"
        "    assert cmd[1:4] == ['-m', 'hyperresearch', 'install']\n"
        f"    return popen([sys.executable, {str(install_child)!r}], **kwargs)\n"
        "subprocess.Popen = delegate\n"
        "app()\n", encoding="utf-8",
    )
    process = subprocess.Popen(
        [sys.executable, str(launcher), "setup", str(tmp_path), *args],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not ready_file.exists():
            assert process.poll() is None, process.communicate()
            assert time.monotonic() < deadline, "fake installer did not start"
            time.sleep(0.01)
        os.killpg(process.pid, signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 130, (stdout, stderr)
        with lock_file.open("r+") as lock:
            deadline = time.monotonic() + 5
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    assert time.monotonic() < deadline, "grandchild survived setup Ctrl+C"
                    time.sleep(0.01)
    finally:
        for pid in [process.pid] + (
            [int(installer_pid_file.read_text())] if installer_pid_file.exists() else []
        ):
            try:
                os.killpg(pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
        process.communicate(timeout=5)
