"""The CLI's Python version warning matches the versions the package supports.

pyproject allows `>=3.11,<3.15` and lists 3.14, and the suite passes there,
but the import-time guard still tested `>= (3, 14)` and told every 3.14 user
the version "is not yet supported. Please use Python 3.11, 3.12, or 3.13".
The guard now starts at 3.15.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

# Import the CLI package under a faked interpreter version. The guard runs
# before any third-party import; whatever a dependency does with the fake
# version afterwards is swallowed, since only the guard's output matters.
PROBE = """
import collections, sys
V = collections.namedtuple("V", "major minor micro releaselevel serial")
sys.version_info = V({major}, {minor}, 0, "final", 0)
try:
    import hyperresearch.cli
except BaseException:
    pass
"""


def _stderr_under(major: int, minor: int) -> str:
    env = {k: v for k, v in os.environ.items() if k != "HYPERRESEARCH_SKIP_PYVER_CHECK"}
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(SRC), env.get("PYTHONPATH")) if p)
    proc = subprocess.run(
        [sys.executable, "-c", PROBE.format(major=major, minor=minor)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    return proc.stderr


@pytest.mark.parametrize("minor", [11, 12, 13, 14])
def test_supported_versions_get_no_warning(minor):
    assert "not yet supported" not in _stderr_under(3, minor)


def test_the_first_unsupported_version_is_warned_about():
    err = _stderr_under(3, 15)
    assert "Python 3.15 is not yet supported" in err
    assert "3.14" in err
