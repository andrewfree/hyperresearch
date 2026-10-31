import json

from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.hooks import install_hooks
from hyperresearch.core.runs import init_run, verify_run


def test_custom_research_dir_report(tmp_vault, monkeypatch):
    vault = tmp_vault
    vault.config.research_dir = "kb"
    vault.config.save(vault.config_path)
    tag = "rd-eeeeee"
    init_run(vault, tag)
    vault.notes_dir.mkdir(parents=True)
    report = vault.notes_dir / f"final_report_{tag}.md"
    report.write_text("# Report\n\nA claim [[missing-note]].\n")
    monkeypatch.chdir(vault.root)
    result = CliRunner().invoke(app, ["citecheck", "extract", tag, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["ok"]
    check = next(c for c in verify_run(vault, tag)["checks"] if c["name"] == "report-exists")
    assert check["ok"]


def test_custom_research_dir_prompts(tmp_vault):
    tmp_vault.config.research_dir = "kb"
    tmp_vault.config.save(tmp_vault.config_path)
    install_hooks(tmp_vault.root)
    prompts = list((tmp_vault.root / ".claude").rglob("*.md"))
    reports = [p.read_text() for p in prompts if "final_report_" in p.read_text()]
    assert reports
    assert all("research/notes/final_report_" not in text for text in reports)
    assert any("kb/notes/final_report_" in text for text in reports)
