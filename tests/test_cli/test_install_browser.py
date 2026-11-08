"""Browser-setup installer preference: patchright's chromium when present.

The stealth adapter (UndetectedAdapter) launches patchright's pinned chromium,
which lives in a separate registry from plain playwright's. A setup that only
runs `playwright install chromium` produces a machine where every preflight
passes and every browser fetch dies at launch. These tests pin the installer
order without touching the network or any real browser registry.
"""

from __future__ import annotations

import importlib
import json
import subprocess
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest

pytestmark = pytest.mark.browser_setup

from hyperresearch.cli.install import _setup_crawl4ai


@pytest.fixture(autouse=True)
def _no_working_browser(monkeypatch):
    """Force the availability check down the install path: both sync_api
    imports fail, so _setup_crawl4ai must decide which installer to run."""
    monkeypatch.setitem(sys.modules, "crawl4ai", ModuleType("crawl4ai"))
    monkeypatch.setitem(sys.modules, "patchright.sync_api", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)


def _capture_installs(monkeypatch, fail_mods=()):
    calls: list[str] = []

    def fake_run(cmd):
        mod = cmd[2]
        calls.append(mod)
        if mod in fail_mods:
            import subprocess

            raise subprocess.CalledProcessError(1, cmd)
        return None

    monkeypatch.setattr("hyperresearch.cli._browser.run_installer", fake_run)
    return calls


def test_patchright_chromium_preferred_when_patchright_present(
        tmp_vault, monkeypatch, _no_working_browser):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    calls = _capture_installs(monkeypatch)

    assert _setup_crawl4ai(tmp_vault) == "browser_installed"
    assert calls == ["patchright"], (
        "with patchright installed, its own chromium must be installed first; "
        "plain `playwright install chromium` does not provide it"
    )


def test_plain_playwright_used_when_patchright_absent(
        tmp_vault, monkeypatch, _no_working_browser):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    calls = _capture_installs(monkeypatch)

    assert _setup_crawl4ai(tmp_vault) == "browser_installed"
    assert calls == ["playwright"]


def test_failed_patchright_install_falls_back_to_playwright(
        tmp_vault, monkeypatch, _no_working_browser):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    calls = _capture_installs(monkeypatch, fail_mods=("patchright",))

    assert _setup_crawl4ai(tmp_vault) == "browser_installed"
    assert calls == ["patchright", "playwright"]


@pytest.mark.parametrize("command", ["install", "setup"])
def test_browser_timeout_tries_fallback(tmp_vault, monkeypatch, command):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    calls = []

    def install(cmd):
        calls.append(cmd[2])
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr("hyperresearch.cli._browser.run_installer", install)
    if command == "install":
        assert _setup_crawl4ai(tmp_vault) == "browser_failed"
    else:
        importlib.import_module("hyperresearch.cli.setup")._ensure_browser()
    assert calls == ["patchright", "playwright"]


@pytest.mark.parametrize("command", ["install", "setup"])
def test_browser_timeout_reports_manual_install_advice(tmp_vault, monkeypatch, capsys, command):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)

    def timeout(cmd):
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr("hyperresearch.cli._browser.run_installer", timeout)
    if command == "install":
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        result = CliRunner().invoke(app, ["install", str(tmp_vault.root)])
        assert result.exit_code == 0, result.output
        output = result.output
        assert "browser ready" not in output
        assert "crawl4ai:" in output
        assert "set as default provider" in output
        assert output.index("crawl4ai:") < output.index("Could not install browser")
    else:
        importlib.import_module("hyperresearch.cli.setup")._ensure_browser()
        output = capsys.readouterr().out
    assert "Could not install browser automatically" in output
    assert "playwright install chromium" in output
    assert "python -m patchright install chromium" in output


@pytest.mark.parametrize("command", ["install", "install-json", "setup"])
def test_failed_tree_cleanup_reports_failure_without_fallback(
        tmp_vault, monkeypatch, capsys, command):
    from hyperresearch.cli import _browser

    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr(_browser, "_WINDOWS", True)
    process = Mock(pid=4321)
    process.wait.side_effect = subprocess.TimeoutExpired("installer", 300)
    popen = Mock(return_value=process)
    monkeypatch.setattr(_browser.subprocess, "Popen", popen)
    taskkill = Mock(side_effect=subprocess.CalledProcessError(1, "taskkill"))
    monkeypatch.setattr(_browser.subprocess, "run", taskkill)

    if command.startswith("install"):
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        args = ["install", str(tmp_vault.root)]
        if command == "install-json":
            args.append("--json")
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, result.exception
        output = result.output
        if command == "install-json":
            envelope = json.loads(output)
            assert envelope["data"]["crawl4ai"] == "browser_failed"
            assert envelope["ok"] is True
        else:
            assert "crawl4ai:" in output
            assert "set as default provider" in output
            assert output.index("crawl4ai:") < output.index("Could not install browser")
        assert tmp_vault.config.load(tmp_vault.config_path).web_provider == "crawl4ai"
    else:
        importlib.import_module("hyperresearch.cli.setup")._ensure_browser()
        output = capsys.readouterr().out
    if command != "install-json":
        assert "Could not install browser automatically" in output
        assert "playwright install chromium" in output
        assert "python -m patchright install chromium" in output
        assert "browser ready" not in output.lower()
    assert popen.call_count == 1, "an unconfirmed cleanup must not start the fallback"
    assert popen.call_args.args[0][2] == "patchright"
    taskkill.assert_called_once()


@pytest.mark.parametrize("command", ["install", "install-json", "setup"])
@pytest.mark.parametrize("cleanup_error", [OSError, subprocess.CalledProcessError])
def test_failed_windows_cleanup_does_not_swallow_ctrl_c(
        tmp_vault, monkeypatch, command, cleanup_error):
    from hyperresearch.cli import _browser

    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    monkeypatch.setattr(_browser, "_WINDOWS", True)
    process = Mock(pid=4321)
    process.wait.side_effect = KeyboardInterrupt
    popen = Mock(return_value=process)
    monkeypatch.setattr(_browser.subprocess, "Popen", popen)
    error = cleanup_error(1, "taskkill")
    monkeypatch.setattr(_browser.subprocess, "run", Mock(side_effect=error))
    if command == "setup":
        with pytest.raises(KeyboardInterrupt):
            importlib.import_module("hyperresearch.cli.setup")._ensure_browser()
    else:
        from typer.testing import CliRunner

        from hyperresearch.cli import app

        args = ["install", str(tmp_vault.root)]
        if command == "install-json":
            args.append("--json")
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 130, result.output
        assert "browser_failed" not in result.output
        assert "INSTALL_ERROR" not in result.output
    assert popen.call_count == 1


@pytest.mark.parametrize("error_type", [KeyboardInterrupt, SystemExit, RuntimeError])
def test_failed_windows_cleanup_preserves_original_exception(monkeypatch, error_type):
    from hyperresearch.cli import _browser

    monkeypatch.setattr(_browser, "_WINDOWS", True)
    error = error_type("interrupted wait")
    process = Mock(pid=4321)
    process.wait.side_effect = error
    monkeypatch.setattr(_browser.subprocess, "Popen", Mock(return_value=process))
    monkeypatch.setattr(_browser.subprocess, "run", Mock(side_effect=OSError("taskkill failed")))
    with pytest.raises(error_type) as caught:
        _browser.run_installer(["installer"])
    assert caught.value is error
