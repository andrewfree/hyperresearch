import json

from typer.testing import CliRunner

from hyperresearch.cli import app


def test_first_install_reports_appended_docs(tmp_path, monkeypatch):
    monkeypatch.setattr("hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed")
    doc = tmp_path / "CLAUDE.md"
    doc.write_text("# My project\nUser rules.\n")
    runner = CliRunner()
    result = runner.invoke(app, ["install", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    assert "CLAUDE.md (appended)" in json.loads(result.output)["data"]["agent_docs"]
    assert doc.read_text().count("hyperresearch:start") == 1
    again = runner.invoke(app, ["install", str(tmp_path), "--json"])
    assert json.loads(again.output)["data"]["agent_docs"] == []
