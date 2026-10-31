"""`export vault` knows the vault by the directory, not by how it is spelled.

The check compared resolved paths as strings, and on a case-insensitive
filesystem (macOS, Windows) resolve() keeps the case that was typed: the
vault root spelled in other case still crashed with SameFileError, and
./RESEARCH/x copied every note into research/x/, where each sync reported
the copies as id collisions.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path / "vault")]).exit_code == 0
    if not (tmp_path / "VAULT").exists():
        pytest.skip("needs a case-insensitive filesystem")
    monkeypatch.chdir(tmp_path / "vault")
    assert runner.invoke(app, ["note", "new", "Alpha", "-b", "body"]).exit_code == 0
    return tmp_path / "vault"


def _tree(root: Path) -> dict[str, bytes]:
    research = root / "research"
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in research.rglob("*") if p.is_file()}


@pytest.mark.parametrize("dest", ["../VAULT", "RESEARCH", "Research/x", "RESEARCH/notes/sub"])
def test_export_into_the_vault_in_other_case_is_refused(root, dest):
    before = _tree(root)
    result = runner.invoke(app, ["export", "vault", dest, "--json"])
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    envelope = json.loads(result.stdout)
    assert envelope["error_code"] == "EXPORT_INTO_VAULT"
    assert _tree(root) == before


def test_other_directories_inside_the_vault_still_work(root):
    result = runner.invoke(app, ["export", "vault", ".HYPERRESEARCH/exports/subset", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["count"] == 1
