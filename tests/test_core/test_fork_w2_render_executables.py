import pytest

from hyperresearch.core.hooks import install_hooks


@pytest.mark.parametrize("platform", ["claude", "codex"])
@pytest.mark.parametrize("windows", [False, True])
def test_custom_research_dir_keeps_agent_executable(tmp_vault, platform, windows):
    tmp_vault.config.research_dir = "kb"
    tmp_vault.config.save(tmp_vault.config_path)
    executable = str(tmp_vault.root / "research" / "bin" / "hyperresearch")
    if windows:
        executable = "C:" + executable.replace("/", "\\")
    install_hooks(tmp_vault.root, hpr_path=executable, platform=platform)
    if platform == "claude":
        agent = tmp_vault.root / ".claude/agents/hyperresearch-cite-checker.md"
    else:
        agent = tmp_vault.root / ".codex/agents/hyperresearch-cite-checker.toml"
    text = agent.read_text()
    assert executable.replace("\\", "/") in text
    assert "kb/runs/<vault_tag>/cite-check-pairs.json" in text
