"""A hook the installer refused is reported as not installed, never as done.

Installers returned the refusal as an ordinary action string, so `profile use
--json` listed it under `rerendered`, `install` printed it under a green
"Hooks installed:" header, and the one caller that noticed did so by looking
for the words "NOT installed". Refusals are now a distinct type: `profile use
--json` lists them under `refused`, and the text output prints them under a
yellow "Not installed:" header.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.hooks import _install_claude_hook, _install_codex_stop_hook

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


def _break_settings(root):
    path = root / ".claude" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad", encoding="utf-8")


def test_installers_return_a_refusal_type(tmp_path):
    from hyperresearch.core.hooks import HookRefusal

    ok_root = tmp_path / "ok"
    ok_root.mkdir()
    installed = _install_claude_hook(ok_root, "hyperresearch")
    assert installed is not None and not isinstance(installed, HookRefusal)

    bad_root = tmp_path / "bad"
    _break_settings(bad_root)
    refused = _install_claude_hook(bad_root, "hyperresearch")
    assert isinstance(refused, HookRefusal)

    hooks_json = bad_root / ".codex" / "hooks.json"
    hooks_json.parent.mkdir(parents=True)
    hooks_json.write_text("{bad", encoding="utf-8")
    assert isinstance(_install_codex_stop_hook(bad_root, "hyperresearch"), HookRefusal)


def test_profile_use_json_lists_a_refusal_apart_from_rerendered_files(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    assert runner.invoke(app, ["install", str(tmp_vault.root), "--json"]).exit_code == 0
    _break_settings(tmp_vault.root)

    result = runner.invoke(app, ["profile", "use", "full", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert not any(".claude/settings.json" in a for a in data["rerendered"])
    [refusal] = data["refused"]
    assert ".claude/settings.json is not valid JSON" in refusal


def test_profile_use_json_has_an_empty_refused_list_when_nothing_was_refused(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)

    result = runner.invoke(app, ["profile", "use", "premier", "--json"])

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["refused"] == []
    assert data["rerendered"]


def test_install_prints_a_refusal_under_not_installed(tmp_vault, monkeypatch):
    _break_settings(tmp_vault.root)
    monkeypatch.chdir(tmp_vault.root)

    result = runner.invoke(app, ["install", str(tmp_vault.root)])

    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "Not installed:" in out
    refusal_at = out.index(".claude/settings.json is not valid JSON")
    assert out.index("Not installed:") < refusal_at
    installed_at = out.find("Hooks installed:")
    if installed_at != -1:
        # The refusal is not inside the "Hooks installed:" list.
        assert not (installed_at < refusal_at < out.index("Not installed:"))


def test_install_reports_only_the_refusal_when_everything_else_is_current(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    assert runner.invoke(app, ["install", str(tmp_vault.root), "--json"]).exit_code == 0
    _break_settings(tmp_vault.root)

    result = runner.invoke(app, ["install", str(tmp_vault.root)])

    assert result.exit_code == 0, result.output
    assert "Hooks installed:" not in result.stdout
    assert "All hooks already installed" not in result.stdout
    assert "Not installed:" in result.stdout


class _TTY:
    def isatty(self) -> bool:
        return True


def test_setup_prints_a_refusal_as_not_installed(tmp_vault, monkeypatch):
    import sys
    import types

    import hyperresearch.cli.setup as setup_module

    # The interactive route needs a terminal; crawl4ai absent means it asks
    # nothing.
    monkeypatch.setattr(
        setup_module, "sys", types.SimpleNamespace(stdin=_TTY(), executable=sys.executable)
    )
    monkeypatch.setattr(setup_module, "_check_crawl4ai", lambda: False)
    _break_settings(tmp_vault.root)

    result = runner.invoke(app, ["setup", str(tmp_vault.root)])

    assert result.exit_code == 0, result.output
    out = " ".join(result.stdout.split())
    assert "Not installed: Claude Code: .claude/settings.json is not valid JSON" in out
    assert "Hook: Claude Code: .claude/settings.json" not in out
