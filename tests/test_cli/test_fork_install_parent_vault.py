"""install inside an existing vault installs into that vault, as it reports.

`install child/` found the parent vault (reporting `"vault": "existing"` and
the parent's path) but wrote hook.js, CLAUDE.md and .claude/ under child/.
The `.hyperresearch/` dir that hook.js lives in made child/ a vault root of its
own, so the next `note new` from there went to a new, empty vault instead of
the parent. Every file now goes under the vault root install reports.
"""

from __future__ import annotations

import json
import sys
import types

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


@pytest.fixture
def parent(tmp_path, monkeypatch):
    root = tmp_path / "parent"
    root.mkdir()
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["install", str(root), "--json"]).exit_code == 0
    (root / "child").mkdir()
    return root


@pytest.mark.parametrize("target", ["claude", "codex"])
def test_install_from_a_subdirectory_writes_into_the_parent_vault(parent, monkeypatch, target):
    child = parent / "child"
    monkeypatch.chdir(child)

    result = runner.invoke(app, ["install", str(child), "--target", target, "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["vault"] == "existing"
    assert data["vault_path"] == str(parent)
    assert list(child.iterdir()) == []
    if target == "codex":
        assert (parent / "AGENTS.md").is_file()
        assert (parent / ".agents" / "skills" / "hyperresearch" / "SKILL.md").is_file()

    note = runner.invoke(app, ["note", "new", "Child note", "--body", "hi", "--json"])
    assert note.exit_code == 0, note.output
    assert json.loads(note.stdout)["vault"] == str(parent)


def test_install_from_a_subdirectory_says_where_it_installed(parent, monkeypatch):
    child = parent / "child"
    monkeypatch.chdir(child)

    result = runner.invoke(app, ["install", str(child)])

    assert result.exit_code == 0, result.output
    # Rich wraps long paths, so compare with all whitespace removed.
    out = "".join(result.stdout.split())
    assert "Vaultexists:" + "".join(str(parent).split()) in out
    assert "isinsidethevault" in out
    assert list(child.iterdir()) == []


class _TTY:
    def isatty(self) -> bool:
        return True


def test_interactive_install_in_a_subdirectory_skips_first_time_setup(parent, monkeypatch, capsys):
    from hyperresearch.cli.install import install

    child = parent / "child"
    monkeypatch.chdir(child)
    monkeypatch.setattr(sys, "stdin", _TTY())
    monkeypatch.setattr(
        "hyperresearch.cli.setup.setup",
        lambda **kw: pytest.fail("first-time setup ran inside an existing vault"),
    )

    install(
        path=str(child), name="Research Base", json_output=False, global_install=False,
        steps_only=False, create=False, profile=None, target="claude",
    )

    assert list(child.iterdir()) == []


def test_setup_from_a_subdirectory_writes_into_the_parent_vault(parent, monkeypatch):
    import hyperresearch.cli.setup as setup_module

    child = parent / "child"
    monkeypatch.chdir(child)
    monkeypatch.setattr(
        setup_module, "sys", types.SimpleNamespace(stdin=_TTY(), executable=sys.executable)
    )
    monkeypatch.setattr(setup_module, "_check_crawl4ai", lambda: False)

    result = runner.invoke(app, ["setup", str(child)])

    assert result.exit_code == 0, result.output
    assert list(child.iterdir()) == []
