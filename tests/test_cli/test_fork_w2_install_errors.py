import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app


@pytest.fixture(autouse=True)
def offline_install(monkeypatch):
    monkeypatch.setattr("hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed")


def test_install_preserves_non_utf8_docs(tmp_path):
    doc = tmp_path / "CLAUDE.md"
    doc.write_bytes(b"# Caf\xe9\n")
    for _ in range(2):
        result = CliRunner().invoke(app, ["install", str(tmp_path), "--json"])
        assert result.exit_code == 0, repr(result.exception)
        data = json.loads(result.output)["data"]
        assert any("skipped" in action and "UTF-8" in action for action in data["agent_docs"])
        assert doc.read_bytes() == b"# Caf\xe9\n"


@pytest.mark.parametrize("args", [[], ["--steps-only"]])
def test_install_readonly_directory_envelope(tmp_path, args):
    tmp_path.chmod(0o555)
    try:
        result = CliRunner().invoke(app, ["install", str(tmp_path), *args, "--json"])
        assert result.exit_code == 1
        assert json.loads(result.output)["error_code"] == "INSTALL_ERROR"
    finally:
        tmp_path.chmod(0o755)


@pytest.mark.parametrize("settings", [{"hooks": []}, {"hooks": {"PreToolUse": {}}}])
def test_install_preserves_malformed_settings(tmp_path, settings):
    config = tmp_path / ".claude" / "settings.json"
    config.parent.mkdir()
    original = json.dumps(settings)
    config.write_text(original)
    result = CliRunner().invoke(app, ["install", str(tmp_path), "--json"])
    assert result.exit_code == 0, repr(result.exception)
    assert config.read_text() == original
    assert any("NOT installed" in action for action in json.loads(result.output)["data"]["hooks_installed"])
