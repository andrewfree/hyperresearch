"""Run browser installers with bounded waits and process tree cleanup."""

import os
import signal
import subprocess
import sys

_WINDOWS = sys.platform == "win32"


def run_installer(command: list[str], *, timeout: float = 300) -> None:
    """Stop the installer and its children before reporting a timeout."""
    options = {"creationflags": 0x200} if _WINDOWS else {"start_new_session": True}
    # CREATE_NEW_PROCESS_GROUP is 0x200 on Windows. Keep output off pipes:
    # driver children can inherit them and prevent timeout cleanup finishing.
    process = subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options,
    )
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        if _WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/T", "/F", "/PID", str(process.pid)],
                    check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                # Do not start a fallback while the old driver may still run.
                raise RuntimeError("Could not stop the timed-out browser installer tree") from exc
        else:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        process.wait()
        raise
    if returncode:
        raise subprocess.CalledProcessError(returncode, command)
