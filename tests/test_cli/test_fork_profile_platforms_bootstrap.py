"""A project bootstrapped from a global install counts as installed for its runtime.

After `install --global`, the entry skill lives under the home directory and
the first run in a project only adds the step procedures (`install
--steps-only`). `installed_platforms` looked for the project's own entry
skill, so such a Codex project read as having nothing installed: `profile
use` fell back to Claude Code, added a .claude/ install, and left the Codex
step files at the old gear.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.hooks import installed_platforms

runner = CliRunner()


def _run(*args):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, result.output
    return result


@pytest.fixture
def bootstrapped(tmp_path, monkeypatch):
    """What the entry skill's first-run bootstrap leaves in a project."""

    def make(target):
        root = tmp_path / f"proj-{target}"
        root.mkdir()
        monkeypatch.chdir(root)
        _run("init", str(root), "--json")
        _run("install", str(root), "--steps-only", "--target", target, "--json")
        return root

    return make


@pytest.mark.parametrize("target", ["claude", "codex"])
def test_a_steps_only_install_is_detected(bootstrapped, target):
    assert installed_platforms(bootstrapped(target)) == [target]


def test_profile_use_rerenders_a_bootstrapped_codex_project_without_adding_claude(
    bootstrapped,
):
    root = bootstrapped("codex")

    result = _run("profile", "use", "premier", "--json")

    assert not (root / ".claude").exists()
    step = root / ".hyperresearch" / "codex" / "steps" / "hyperresearch-1-decompose.md"
    assert 'rendered from profile "premier"' in step.read_text(encoding="utf-8")
    rerendered = json.loads(result.stdout)["data"]["rerendered"]
    assert rerendered and all(a.startswith("Codex:") for a in rerendered)


def test_config_agent_docs_writes_agents_md_for_a_bootstrapped_codex_project(bootstrapped):
    root = bootstrapped("codex")

    _run("config", "agent-docs", "--json")

    assert not (root / ".claude").exists()
    assert "hyperresearch:start" in (root / "AGENTS.md").read_text(encoding="utf-8")


def test_a_vault_with_nothing_installed_is_still_detected_as_nothing(tmp_path):
    _run("init", str(tmp_path), "--json")
    assert installed_platforms(tmp_path) == []
