"""The interactive setup route honours --name and --profile, and keeps a vault's name.

On a terminal, a first-time `install` hands over to the setup TUI, which was
called with the path alone: the vault was named "Research Base" and the skills
rendered from "full" whatever --name and --profile said, with no warning. The
TUI also wrote its hardcoded "Research Base" over an existing vault's name on
every re-run. setup now takes --name and --profile, install passes them on,
and an existing vault keeps its name.
"""

from __future__ import annotations

import sys
import types

import pytest
from typer.testing import CliRunner

import hyperresearch.cli.setup as setup_cli
from hyperresearch.cli import app
from hyperresearch.core.config import VaultConfig

runner = CliRunner()


class _TTY:
    def isatty(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _quiet_setup(monkeypatch):
    # Without crawl4ai the TUI asks nothing; install's own crawl4ai probe may
    # launch or install Chromium.
    monkeypatch.setattr(setup_cli, "_check_crawl4ai", lambda: False)
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


@pytest.fixture
def setup_tty(monkeypatch):
    """Make `setup` (run through CliRunner, which swaps stdin) see a terminal."""
    monkeypatch.setattr(
        setup_cli, "sys", types.SimpleNamespace(stdin=_TTY(), executable=sys.executable)
    )


def _name(root) -> str:
    return VaultConfig.load(root / ".hyperresearch" / "config.toml").name


def _gear(root) -> str:
    sweep = root / ".claude" / "skills" / "hyperresearch-2-width-sweep" / "SKILL.md"
    text = sweep.read_text(encoding="utf-8")
    return text.split('rendered from profile "', 1)[1].split('"', 1)[0]


def _install_on_a_terminal(monkeypatch, root, **flags):
    from hyperresearch.cli.install import install

    monkeypatch.setattr(sys, "stdin", _TTY())
    args = dict(
        path=str(root), name="Research Base", json_output=False, global_install=False,
        steps_only=False, create=False, profile=None, target="claude",
    )
    args.update(flags)
    install(**args)


def test_interactive_first_install_uses_name_and_profile(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.chdir(root)

    _install_on_a_terminal(monkeypatch, root, name="Lab Notebook", profile="premier")

    assert _name(root) == "Lab Notebook"
    assert _gear(root) == "premier"


def test_interactive_first_install_rejects_an_unknown_profile_before_setup(tmp_path, monkeypatch):
    import typer

    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.chdir(root)

    with pytest.raises(typer.Exit):
        _install_on_a_terminal(monkeypatch, root, profile="premeir")

    assert list(root.iterdir()) == []


def test_rerunning_setup_keeps_the_vault_name(tmp_path, monkeypatch, setup_tty):
    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.chdir(root)
    assert runner.invoke(app, ["install", str(root), "--name", "Lab Notebook", "--json"]).exit_code == 0

    result = runner.invoke(app, ["setup", str(root)])

    assert result.exit_code == 0, result.output
    assert _name(root) == "Lab Notebook"


def test_setup_names_a_new_vault_and_renders_the_given_profile(tmp_path, monkeypatch, setup_tty):
    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["setup", str(root), "--name", "Lab Notebook", "--profile", "premier"])

    assert result.exit_code == 0, result.output
    assert _name(root) == "Lab Notebook"
    assert _gear(root) == "premier"


def test_setup_rejects_an_unknown_profile_before_writing(tmp_path, monkeypatch, setup_tty):
    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["setup", str(root), "--profile", "premeir"])

    assert result.exit_code == 1
    assert "premeir" in result.output
    assert list(root.iterdir()) == []


def test_non_interactive_setup_passes_the_flags_to_install(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr("subprocess.call", lambda cmd: calls.append(cmd) or 0)

    result = runner.invoke(
        app, ["setup", str(tmp_path), "--name", "Lab Notebook", "--profile", "premier", "--json"]
    )

    assert result.exit_code == 0, result.output
    [cmd] = calls
    assert cmd[cmd.index("--name") + 1] == "Lab Notebook"
    assert cmd[cmd.index("--profile") + 1] == "premier"
    assert "--json" in cmd
