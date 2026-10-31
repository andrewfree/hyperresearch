"""`install --profile <typo>` must fail before it writes anything.

The profile was validated after `Vault.init`, so a typo returned
UNKNOWN_PROFILE but left `.hyperresearch/`, `research/` and CLAUDE.md behind,
and the next install then saw an existing vault. The check now runs first.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


@pytest.mark.parametrize("target", ["claude", "codex", "all"])
def test_unknown_profile_leaves_a_fresh_directory_empty(tmp_path, monkeypatch, target):
    root = tmp_path / "fresh"
    root.mkdir()
    monkeypatch.chdir(root)

    result = runner.invoke(
        app, ["install", str(root), "--profile", "premeir", "--target", target, "--json"]
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "UNKNOWN_PROFILE"
    assert list(root.iterdir()) == []


def test_unknown_profile_in_text_mode_leaves_a_fresh_directory_empty(tmp_path, monkeypatch):
    root = tmp_path / "fresh"
    root.mkdir()
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root), "--profile", "premeir"])

    assert result.exit_code == 1
    assert "premeir" in result.output
    assert list(root.iterdir()) == []


def test_a_valid_profile_still_installs(tmp_path, monkeypatch):
    root = tmp_path / "fresh"
    root.mkdir()
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root), "--profile", "premier", "--json"])

    assert result.exit_code == 0, result.output
    sweep = root / ".claude" / "skills" / "hyperresearch-2-width-sweep" / "SKILL.md"
    assert 'rendered from profile "premier"' in sweep.read_text(encoding="utf-8")
