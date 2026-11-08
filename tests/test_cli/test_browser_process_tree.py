"""Interrupted browser installers stop descendants before another can start."""

import os
import signal
import subprocess
import sys
import time
from threading import Timer
from unittest.mock import Mock

import pytest


@pytest.mark.parametrize("interruption", [
    "timeout", "keyboard_interrupt", "wait_error", "SIGTERM", "SIGHUP",
])
def test_installer_interruption_kills_real_posix_tree(tmp_path, monkeypatch, interruption):
    if sys.platform == "win32":
        pytest.skip("POSIX process groups and signals; Windows cleanup is tested through a seam")
    import fcntl

    from hyperresearch.cli import _browser

    pid_file = tmp_path / "grandchild.pid"
    lock_file = tmp_path / "grandchild.lock"
    script = tmp_path / "installer.py"
    grandchild = (
        "import fcntl, os, pathlib, sys, time; "
        "lock = open(sys.argv[2], 'w'); "
        "fcntl.flock(lock, fcntl.LOCK_EX); "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )
    child = (
        "import fcntl, subprocess, sys, time; "
        "lock = open(sys.argv[2] + '.child', 'w'); "
        "fcntl.flock(lock, fcntl.LOCK_EX); "
        f"subprocess.Popen([sys.executable, '-c', {grandchild!r}, *sys.argv[1:]]); "
        "time.sleep(60)"
    )
    script.write_text(
        "import subprocess, sys, time\n"
        f"subprocess.Popen([sys.executable, '-c', {child!r}, *sys.argv[1:]])\n"
        "time.sleep(60)\n", encoding="utf-8",
    )
    real_popen = subprocess.Popen
    processes = []
    timers = []
    tree_stopped = False
    watched_signals = (signal.SIGTERM, signal.SIGHUP)
    previous_handlers = {sig: signal.getsignal(sig) for sig in watched_signals}

    def unexpected_signal(signum, frame):
        raise AssertionError(f"installer did not handle signal {signum}")

    for sig in watched_signals:
        signal.signal(sig, unexpected_signal)

    def popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        processes.append(process)
        real_wait = process.wait

        def wait(timeout=None):
            if timeout is None:
                return real_wait()
            deadline = time.monotonic() + 5
            while not pid_file.exists():
                assert time.monotonic() < deadline, "grandchild did not start"
                time.sleep(0.01)
            if interruption == "keyboard_interrupt":
                raise KeyboardInterrupt
            if interruption == "wait_error":
                raise RuntimeError("wait failed")
            if interruption.startswith("SIG"):
                timer = Timer(0.05, os.kill, (os.getpid(), getattr(signal, interruption)))
                timers.append(timer)
                timer.start()
            return real_wait(timeout=timeout)

        process.wait = wait
        return process

    monkeypatch.setattr(_browser.subprocess, "Popen", popen)
    expected_error = {
        "timeout": subprocess.TimeoutExpired,
        "keyboard_interrupt": KeyboardInterrupt,
        "wait_error": RuntimeError,
        "SIGTERM": SystemExit,
        "SIGHUP": SystemExit,
    }[interruption]
    try:
        with pytest.raises(expected_error) as caught:
            _browser.run_installer(
                [sys.executable, str(script), str(pid_file), str(lock_file)], timeout=2,
            )
        if interruption.startswith("SIG"):
            assert caught.value.code == 128 + getattr(signal, interruption)
        assert all(signal.getsignal(sig) is unexpected_signal for sig in watched_signals)
        assert processes[0].returncode is not None, "installer was not reaped"
        deadline = time.monotonic() + 5
        for descendant_lock in (lock_file, lock_file.with_name(lock_file.name + ".child")):
            with descendant_lock.open("r+") as lock:
                while True:
                    try:
                        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        assert time.monotonic() < deadline, "descendant survived and still holds its lock"
                        time.sleep(0.05)
        tree_stopped = True
    finally:
        for timer in timers:
            timer.cancel()
            timer.join()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
        for process in processes:
            if not tree_stopped:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait()


@pytest.mark.parametrize("windows", [False, True])
@pytest.mark.parametrize("error_type", [
    subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit, RuntimeError,
])
def test_timeout_terminates_tree_then_waits(monkeypatch, windows, error_type):
    if not windows and sys.platform == "win32":
        pytest.skip("The POSIX branch needs os.killpg and signal.SIGKILL, which Windows lacks")
    from hyperresearch.cli import _browser

    monkeypatch.setattr(_browser, "_WINDOWS", windows)
    events = []
    command = ["python", "-m", "playwright", "install", "chromium"]
    process = Mock(pid=4321)
    error = (
        subprocess.TimeoutExpired(command, 0.1)
        if error_type is subprocess.TimeoutExpired else error_type("interrupted wait")
    )
    def wait(timeout=None):
        events.append(("wait", timeout))
        if timeout is not None:
            raise error
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
    with pytest.raises(error_type) as caught:
        _browser.run_installer(command, timeout=0.1)
    assert caught.value is error
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

    handlers = (
        {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}
        if sys.platform != "win32" else {}
    )
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
    assert all(signal.getsignal(sig) == handler for sig, handler in handlers.items())


def test_failed_windows_tree_cleanup_does_not_report_retryable_timeout(monkeypatch):
    from hyperresearch.cli import _browser

    monkeypatch.setattr(_browser, "_WINDOWS", True)
    process = Mock(pid=4321)
    process.wait.side_effect = subprocess.TimeoutExpired("installer", 300)
    monkeypatch.setattr(_browser.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(_browser.subprocess, "run", Mock(side_effect=subprocess.CalledProcessError(1, "taskkill")))
    with pytest.raises(RuntimeError, match="Could not stop"):
        _browser.run_installer(["installer"])


@pytest.mark.parametrize("ignored_signal", ["SIGTERM", "SIGHUP"])
def test_installer_preserves_ignored_signals(monkeypatch, ignored_signal):
    if sys.platform == "win32":
        pytest.skip("POSIX signal dispositions")
    from hyperresearch.cli import _browser

    sig = getattr(signal, ignored_signal)
    previous = signal.signal(sig, signal.SIG_IGN)
    process = Mock()

    def wait(timeout):
        assert signal.getsignal(sig) == signal.SIG_IGN
        os.kill(os.getpid(), sig)
        return 0

    process.wait.side_effect = wait
    monkeypatch.setattr(_browser.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(_browser.os, "killpg", Mock())
    try:
        _browser.run_installer(["installer"])
        assert signal.getsignal(sig) == signal.SIG_IGN
    finally:
        signal.signal(sig, previous)


@pytest.mark.parametrize("kill_error", [PermissionError, ProcessLookupError])
@pytest.mark.parametrize("wait_error", [subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit])
def test_gone_posix_group_is_reaped_without_masking_wait_error(monkeypatch, kill_error, wait_error):
    if sys.platform == "win32":
        pytest.skip("POSIX process groups")
    from hyperresearch.cli import _browser

    error = subprocess.TimeoutExpired("installer", 300) if wait_error is subprocess.TimeoutExpired else wait_error(143)
    process = Mock(pid=4321)
    process.wait.side_effect = [error, 0]
    monkeypatch.setattr(_browser.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(_browser.os, "killpg", Mock(side_effect=kill_error()))
    with pytest.raises(wait_error) as caught:
        _browser.run_installer(["installer"])
    assert caught.value is error
    assert process.wait.call_count == 2
    assert process.wait.call_args.args == ()
    assert process.wait.call_args.kwargs == {}


def test_installer_works_from_worker_thread():
    from concurrent.futures import ThreadPoolExecutor

    from hyperresearch.cli._browser import run_installer

    with ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(run_installer, [sys.executable, "-c", "pass"]).result(timeout=10)
