"""install prunes only skill and agent files it rendered, and only those files.

The ownership test was "SKILL.md mentions hyperresearch", which a user's own
skill in a project that runs hyperresearch naturally does, and retired agent
files were deleted on their name alone. A matching directory was then removed
with shutil.rmtree, taking any other file the user kept in it. Install now
deletes only a file carrying its provenance header (written into every skill
and agent it has rendered since profiles arrived), and removes a directory only
once nothing else is left in it.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.hooks import (
    _prune_global_step_skills,
    _prune_retired_agents,
    install_hooks,
)

runner = CliRunner()

HEADER = '<!-- rendered from profile "full" (hyperresearch 0.13.0) — edit the profile or the package template, not this file -->'


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


def _user_files(root):
    skills = root / ".claude" / "skills"
    workflow = skills / "hyperresearch-my-workflow"
    workflow.mkdir(parents=True)
    (workflow / "SKILL.md").write_text(
        "---\nname: hyperresearch-my-workflow\n"
        "description: My checklist for running hyperresearch on client work\n---\nPrivate.\n",
        encoding="utf-8",
    )
    (workflow / "notes.txt").write_text("private\n", encoding="utf-8")
    research = skills / "research"
    research.mkdir()
    (research / "SKILL.md").write_text(
        "---\nname: research\ndescription: My research helper; calls the hyperresearch CLI.\n"
        "---\nPersonal.\n",
        encoding="utf-8",
    )
    agents = root / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / "hyperresearch-analyst.md").write_text("my own agent\n", encoding="utf-8")
    return [
        workflow / "SKILL.md",
        workflow / "notes.txt",
        research / "SKILL.md",
        agents / "hyperresearch-analyst.md",
    ]


def test_install_keeps_user_skills_and_agents_that_mention_hyperresearch(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    files = _user_files(root)
    before = {f: f.read_bytes() for f in files}
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root), "--json"])

    assert result.exit_code == 0, result.output
    for f, content in before.items():
        assert f.read_bytes() == content, f"{f} was changed or deleted"
    actions = " ".join(json.loads(result.stdout)["data"]["hooks_installed"])
    assert "pruned: hyperresearch-my-workflow" not in actions
    assert "Pruned retired" not in actions
    assert ".claude/skills/research" in actions
    assert ".claude/agents/hyperresearch-analyst.md" in actions


def test_stale_step_skill_we_rendered_is_pruned_but_not_files_beside_it(tmp_path):
    skills = tmp_path / ".claude" / "skills"
    only_ours = skills / "hyperresearch-99-retired"
    only_ours.mkdir(parents=True)
    (only_ours / "SKILL.md").write_text(f"---\nname: x\n---\n{HEADER}\nbody\n", encoding="utf-8")
    shared = skills / "hyperresearch-98-retired"
    shared.mkdir()
    (shared / "SKILL.md").write_text(f"---\nname: y\n---\n{HEADER}\nbody\n", encoding="utf-8")
    (shared / "mine.txt").write_text("keep me\n", encoding="utf-8")

    actions = install_hooks(tmp_path, "hyperresearch")

    assert not only_ours.exists()
    assert not (shared / "SKILL.md").exists()
    assert (shared / "mine.txt").read_text(encoding="utf-8") == "keep me\n"
    assert any("hyperresearch-98-retired" in a and "hyperresearch-99-retired" in a for a in actions)


def test_retired_agent_is_pruned_only_when_we_rendered_it(tmp_path):
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    ours = agents / "hyperresearch-auditor.md"
    ours.write_text(f"---\nname: hyperresearch-auditor\n---\n{HEADER}\n", encoding="utf-8")
    theirs = agents / "hyperresearch-merger.md"
    theirs.write_text("---\nname: hyperresearch-merger\n---\nMerges my hyperresearch runs.\n",
                      encoding="utf-8")

    result = _prune_retired_agents(tmp_path)

    assert not ours.exists()
    assert theirs.exists()
    assert result is not None
    assert "agent hyperresearch-auditor.md" in result
    assert "Left alone (not ours)" in result
    assert ".claude/agents/hyperresearch-merger.md" in result


def test_retired_skill_dir_keeps_files_we_did_not_write(tmp_path):
    research = tmp_path / ".claude" / "skills" / "research"
    research.mkdir(parents=True)
    (research / "SKILL.md").write_text(f"---\nname: research\n---\n{HEADER}\n", encoding="utf-8")
    (research / "reference.md").write_text("notes I wrote\n", encoding="utf-8")

    _prune_retired_agents(tmp_path)

    assert not (research / "SKILL.md").exists()
    assert (research / "reference.md").read_text(encoding="utf-8") == "notes I wrote\n"


def test_global_prune_keeps_a_user_skill_with_a_step_like_name(tmp_path):
    mine = tmp_path / ".claude" / "skills" / "hyperresearch-2-my-sweep"
    mine.mkdir(parents=True)
    (mine / "SKILL.md").write_text(
        "---\nname: hyperresearch-2-my-sweep\n---\nMy own hyperresearch sweep notes.\n",
        encoding="utf-8",
    )
    ours = tmp_path / ".claude" / "skills" / "hyperresearch-2-width-sweep"
    ours.mkdir()
    (ours / "SKILL.md").write_text(f"---\nname: w\n---\n{HEADER}\n", encoding="utf-8")

    result = _prune_global_step_skills(tmp_path)

    assert (mine / "SKILL.md").exists()
    assert not ours.exists()
    assert result is not None and "hyperresearch-2-width-sweep" in result
