"""A hook config whose `hooks` has the wrong shape is refused, not crashed on or overwritten.

`.claude/settings.json` with `"hooks": []` or `"PreToolUse": {...}` parsed as
JSON, so install went on to merge into it and died with an AttributeError
after hook.js was written and before the skills were installed. The Codex
merge instead replaced a non-object `hooks` value with its own, losing what
was there. Both now report the file as NOT installed and leave it unchanged,
and the rest of install still runs.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.hooks import _install_claude_hook, _install_codex_stop_hook

runner = CliRunner()

BAD_SHAPES = [
    {"hooks": []},
    {"hooks": None},
    {"hooks": "PreToolUse"},
    {"hooks": {"PreToolUse": {"matcher": "Bash"}}},
    {"hooks": {"PreToolUse": ["node x.js"]}},
    {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": 3}]}},
    {"hooks": {"Stop": {"hooks": []}}},
]
IDS = ["list", "null", "string", "event-object", "entry-string", "inner-number", "other-event"]


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


def _write(path, data) -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(data, indent=2) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return raw


@pytest.mark.parametrize("data", BAD_SHAPES, ids=IDS)
def test_claude_hook_refuses_a_settings_file_with_misshapen_hooks(tmp_path, data):
    path = tmp_path / ".claude" / "settings.json"
    raw = _write(path, {"model": "opus", **data})

    result = _install_claude_hook(tmp_path, "hyperresearch")

    assert result and "NOT installed" in result and ".claude/settings.json" in result
    assert '"hooks' in result
    assert path.read_bytes() == raw
    assert not (tmp_path / ".hyperresearch" / "hook.js").exists()


@pytest.mark.parametrize("data", BAD_SHAPES, ids=IDS)
def test_codex_hook_refuses_a_hooks_file_with_misshapen_hooks(tmp_path, data):
    path = tmp_path / ".codex" / "hooks.json"
    raw = _write(path, {"other": 1, **data})

    result = _install_codex_stop_hook(tmp_path, "hyperresearch")

    assert result and "NOT installed" in result and ".codex/hooks.json" in result
    assert path.read_bytes() == raw


def test_install_reports_the_refusal_and_still_installs_the_skills(tmp_path, monkeypatch):
    root = tmp_path / "project"
    raw = _write(root / ".claude" / "settings.json", {"hooks": []})
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    [report] = [a for a in payload["data"]["hooks_installed"] if ".claude/settings.json" in a]
    assert "NOT installed" in report
    assert (root / ".claude" / "settings.json").read_bytes() == raw
    assert not (root / ".hyperresearch" / "hook.js").exists()
    assert (root / ".claude" / "skills" / "hyperresearch" / "SKILL.md").is_file()
    assert (root / ".claude" / "agents" / "hyperresearch-fetcher.md").is_file()


def test_codex_install_keeps_a_non_object_hooks_value(tmp_path, monkeypatch):
    root = tmp_path / "project"
    raw = _write(root / ".codex" / "hooks.json", {"hooks": ["keepme"], "other": 1})
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root), "--target", "codex", "--json"])

    assert result.exit_code == 0, result.output
    assert (root / ".codex" / "hooks.json").read_bytes() == raw
    actions = json.loads(result.stdout)["data"]["hooks_installed"]
    assert any(".codex/hooks.json" in a and "NOT installed" in a for a in actions)


def test_well_shaped_hooks_are_still_merged(tmp_path):
    path = tmp_path / ".claude" / "settings.json"
    _write(path, {"hooks": {"PreToolUse": [], "Stop": [{"hooks": []}]}})

    assert _install_claude_hook(tmp_path, "hyperresearch") == (
        "Claude Code: .claude/settings.json (PreToolUse hook)"
    )
    merged = json.loads(path.read_text(encoding="utf-8"))
    assert merged["hooks"]["Stop"] == [{"hooks": []}]
    assert len(merged["hooks"]["PreToolUse"]) == 1
