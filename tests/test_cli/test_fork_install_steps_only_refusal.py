"""`install --steps-only` reports a refused Stop hook apart from the step files.

The Codex entry skill's bootstrap runs `install --steps-only . --target codex`
inside the sandbox, where `.codex/` is read-only, so the Stop hook is often
refused there. The refusal was joined into `steps_installed`, and the text
output printed it under a green "Step skills installed:" header, even on a
re-run where no step file was written.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def _break_hooks_json(root):
    path = root / ".codex" / "hooks.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{bad", encoding="utf-8")


def _steps_only(root, *extra):
    return runner.invoke(
        app, ["install", str(root), "--steps-only", "--target", "codex", *extra]
    )


def test_steps_only_json_lists_a_refused_hook_apart_from_the_steps(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    _break_hooks_json(tmp_vault.root)

    first = _steps_only(tmp_vault.root, "--json")
    again = _steps_only(tmp_vault.root, "--json")

    assert first.exit_code == 0, first.output
    data = json.loads(first.stdout)["data"]
    assert "step files" in data["steps_installed"]
    assert "NOT installed" not in data["steps_installed"]
    [refusal] = data["refused"]
    assert ".codex/hooks.json is not valid JSON" in refusal

    # Nothing left to install: no step-files report, the refusal still shown.
    data = json.loads(again.stdout)["data"]
    assert data["steps_installed"] is None
    [refusal] = data["refused"]
    assert "NOT installed" in refusal


def test_steps_only_json_has_an_empty_refused_list_when_nothing_was_refused(
    tmp_vault, monkeypatch
):
    monkeypatch.chdir(tmp_vault.root)

    result = _steps_only(tmp_vault.root, "--json")

    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["refused"] == []
    assert "Stop hook" in data["steps_installed"]


def test_steps_only_text_prints_a_refusal_under_not_installed(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    _break_hooks_json(tmp_vault.root)
    assert _steps_only(tmp_vault.root).exit_code == 0

    result = _steps_only(tmp_vault.root)

    assert result.exit_code == 0, result.output
    out = " ".join(result.stdout.split())
    assert "Step skills installed" not in out
    assert "Step skills already installed" in out
    assert "Not installed: Codex: .codex/hooks.json is not valid JSON" in out
