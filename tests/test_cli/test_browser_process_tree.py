"""Browser timeouts stop descendants before another installer can start."""

import os
import signal
import subprocess
import sys
import time
from unittest.mock import Mock

import pytest


def test_installer_timeout_kills_real_posix_child(tmp_path):
    if sys.platform == "win32":
        pytest.skip("POSIX process groups; Windows tree termination is tested through a seam")
    import fcntl

    from hyperresearch.cli._browser import run_installer

    pid_file = tmp_path / "child.pid"
    lock_file = tmp_path / "child.lock"
    script = tmp_path / "installer.py"
    child = (
        "import fcntl, os, pathlib, sys, time; "
        "lock = open(sys.argv[2], 'w'); "
        "fcntl.flock(lock, fcntl.LOCK_EX); "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    script.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}, *sys.argv[1:]])\n"
        "time.sleep(60)\n", encoding="utf-8",
    )
    child_stopped = False
    try:
        with pytest.raises(subprocess.TimeoutExpired):
            run_installer([sys.executable, str(script), str(pid_file), str(lock_file)], timeout=2)
        assert pid_file.exists(), "the child must hold the lock before the timeout"
        deadline = time.monotonic() + 5
        with lock_file.open("r+") as lock:
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    child_stopped = True
                    break
                except BlockingIOError:
                    assert time.monotonic() < deadline, "installer child survived and still holds its lock"
                    time.sleep(0.05)
    finally:
        if not child_stopped and pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), signal.SIGKILL)
            except ProcessLookupError:
                pass


@pytest.mark.parametrize("windows", [False, True])
def test_timeout_terminates_tree_then_waits(monkeypatch, windows):
    from hyperresearch.cli import _browser

    monkeypatch.setattr(_browser, "_WINDOWS", windows)
    events = []
    command = ["python", "-m", "playwright", "install", "chromium"]
    process = Mock(pid=4321)
    def wait(timeout=None):
        events.append(("wait", timeout))
        if timeout is not None:
            raise subprocess.TimeoutExpired(command, timeout)
        return -9
    process.wait.side_effect = wait
    popen = Mock(return_value=process)
    monkeypatch.setattr(_browser.subprocess, "Popen", popen)
    def taskkill(cmd, **kwargs):
        events.append(("taskkill", cmd))
        assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["check"] is True
    monkeypatch.setattr(_browser.subprocess, "run", taskkill)
    if not windows:
        monkeypatch.setattr(_browser.os, "killpg", lambda pid, sig: events.append(("killpg", pid, sig)))
    with pytest.raises(subprocess.TimeoutExpired):
        _browser.run_installer(command, timeout=0.1)
    _, kwargs = popen.call_args
    assert kwargs["stdout"] == kwargs["stderr"] == subprocess.DEVNULL
    if windows:
        assert kwargs["creationflags"] == 0x200
        assert not kwargs.get("start_new_session", False)
        assert events[1] == ("taskkill", ["taskkill", "/T", "/F", "/PID", "4321"])
    else:
        assert kwargs["start_new_session"] is True
        assert events[1] == ("killpg", 4321, signal.SIGKILL)
    assert events[0] == ("wait", 0.1)
    assert events[-1] == ("wait", None)


@pytest.mark.parametrize("returncode", [0, 1])
def test_installer_default_timeout_and_exit_status(monkeypatch, returncode):
    from hyperresearch.cli import _browser

    process = Mock()
    process.wait.return_value = returncode
    popen = Mock(return_value=process)
    monkeypatch.setattr(_browser.subprocess, "Popen", popen)
    command = ["python", "installer.py"]
    if returncode:
        with pytest.raises(subprocess.CalledProcessError) as caught:
            _browser.run_installer(command)
        assert caught.value.returncode == returncode
    else:
        _browser.run_installer(command)
    process.wait.assert_called_once_with(timeout=300)
    assert popen.call_args.kwargs["stdout"] == subprocess.DEVNULL
    assert popen.call_args.kwargs["stderr"] == subprocess.DEVNULL


def test_failed_windows_tree_cleanup_does_not_report_retryable_timeout(monkeypatch):
    from hyperresearch.cli import _browser

    monkeypatch.setattr(_browser, "_WINDOWS", True)
    process = Mock(pid=4321)
    process.wait.side_effect = subprocess.TimeoutExpired("installer", 300)
    monkeypatch.setattr(_browser.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(_browser.subprocess, "run", Mock(side_effect=subprocess.CalledProcessError(1, "taskkill")))
    with pytest.raises(RuntimeError, match="Could not stop"):
        _browser.run_installer(["installer"])
