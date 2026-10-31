"""`export vault` refuses a destination that is the vault itself.

Exported to the vault root, each copy's destination was its own source file,
so shutil.copy2 raised SameFileError and --json printed a traceback. Under
the research/ directory the copies would be synced as duplicate notes. Both
are now refused with an error before anything is copied; elsewhere inside
the vault (.hyperresearch/exports/) is still fine.
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
    assert runner.invoke(app, ["init", str(tmp_path / "v")]).exit_code == 0
    monkeypatch.chdir(tmp_path / "v")
    assert runner.invoke(app, ["note", "new", "Alpha", "-b", "body"]).exit_code == 0
    return tmp_path / "v"


def _tree(root: Path) -> dict[str, bytes]:
    research = root / "research"
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in research.rglob("*") if p.is_file()}


@pytest.mark.parametrize("dest", [".", "research", "research/notes/sub", "research/../."])
@pytest.mark.parametrize("dry_run", [False, True])
def test_export_into_the_vault_is_refused(root, dest, dry_run):
    before = _tree(root)
    args = ["export", "vault", dest, "--json"] + (["--dry-run"] if dry_run else [])
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), result.exception
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "EXPORT_INTO_VAULT"
    assert _tree(root) == before


def test_human_mode_is_a_clean_error(root):
    result = runner.invoke(app, ["export", "vault", "."])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), result.exception
    assert "Cannot export into the vault" in result.output


def test_export_outside_the_research_tree_still_works(root, tmp_path):
    for dest in (str(tmp_path / "out"), ".hyperresearch/exports/subset"):
        result = runner.invoke(app, ["export", "vault", dest, "--json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["data"]["count"] == 1
        copy = Path(dest) if Path(dest).is_absolute() else root / dest
        assert (copy / "research" / "notes" / "alpha.md").is_file()
