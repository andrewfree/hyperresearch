import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.runs import init_run


@pytest.mark.parametrize("cmd", [["show"], ["get", "vault.name"], ["set", "vault.name", "X"], ["agent-docs"]])
def test_config_outside_vault_envelope(tmp_path, monkeypatch, cmd):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["config", *cmd, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "NO_VAULT"


def test_run_missing_query_envelope(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    missing = tmp_vault.root / "missing-query.md"
    result = CliRunner().invoke(app, ["run", "init", "q-gggggg", "--query-file", str(missing), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "RUN_ERROR"
    assert not tmp_vault.run_dir("q-gggggg").exists()


def test_escalation_missing_body_envelope(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    runner = CliRunner()
    assert runner.invoke(app, ["escalation", "add", "https://example.org/x", "--reason", "captcha", "--json"]).exit_code == 0
    assert runner.invoke(app, ["escalation", "claim", "--json"]).exit_code == 0
    result = runner.invoke(app, ["escalation", "ingest", "1", "--title", "X", "--body-file", str(tmp_vault.root / "missing-body.md"), "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "ESCALATION_ERROR"


def test_levers_set_corrupt_json_envelope(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    tag = "m-ffffff"
    init_run(tmp_vault, tag)
    decomp = tmp_vault.run_dir(tag) / "prompt-decomposition.json"
    decomp.write_text('{"levers": ')
    result = CliRunner().invoke(app, ["levers", "set", tag, "register=teach", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "LEVER_ERROR"
    assert decomp.read_text() == '{"levers": '


@pytest.mark.parametrize("cmd", ["status", "resume"])
def test_incomplete_manifest_envelope(tmp_vault, monkeypatch, cmd):
    monkeypatch.chdir(tmp_vault.root)
    tag = "m-ffffff"
    init_run(tmp_vault, tag)
    (tmp_vault.run_dir(tag) / "run.json").write_text("{}")
    result = CliRunner().invoke(app, ["run", cmd, tag, "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "RUN_ERROR"
