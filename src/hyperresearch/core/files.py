"""File replacement shared by manifest and index writers."""

import sys
import time
from pathlib import Path

_WINDOWS = sys.platform == "win32"


def replace_file(source: Path, target: Path) -> None:
    """Retry brief Windows sharing violations, then report persistent failures."""
    for attempt in range(5):
        try:
            source.replace(target)
            return
        except PermissionError:
            if not _WINDOWS or attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))
