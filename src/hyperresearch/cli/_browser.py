"""Run browser installers with bounded waits and process tree cleanup."""

import os
import signal
import subprocess
import sys
import threading

_WINDOWS = sys.platform == "win32"


class InstallerCleanupError(RuntimeError):
    """The installer tree may still be running, so a fallback is unsafe."""


def run_installer(command: list[str], *, timeout: float = 300) -> None:
    """Stop the installer and its children if waiting fails or is interrupted."""
    options = {"creationflags": 0x200} if _WINDOWS else {"start_new_session": True}
    # CREATE_NEW_PROCESS_GROUP is 0x200 on Windows. Keep output off pipes:
    # driver children can inherit them and prevent timeout cleanup finishing.
    process = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options,
    )
    previous_handlers = {}

    def interrupt(signum, frame):
        raise SystemExit(128 + signum)

    try:
        if not _WINDOWS and threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGHUP):
                previous_handlers[sig] = signal.signal(sig, interrupt)
        returncode = process.wait(timeout=timeout)
    except BaseException:
        if _WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                # Do not start a fallback while the old driver may still run.
                raise InstallerCleanupError("Could not stop the browser installer tree") from exc
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        raise
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)
