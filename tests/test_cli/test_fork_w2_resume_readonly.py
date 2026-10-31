import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core import runs


@pytest.mark.parametrize("status,reason", [("paused", None), ("blocked", "max_sources")])
def test_resume_readonly_directory_with_writable_lock(tmp_vault, monkeypatch, status, reason):
    tag = "readonly-bbbbbb"
    runs.init_run(tmp_vault, tag)
    runs.set_status(tmp_vault, tag, status, blocked_on=reason)
    run_dir = tmp_vault.run_dir(tag)
    manifest = run_dir / "run.json"
    before = manifest.read_bytes()
    run_dir.chmod(0o555)
    monkeypatch.chdir(tmp_vault.root)
    try:
        result = CliRunner().invoke(app, ["run", "resume", tag, "--json"])
        assert result.exit_code == 1
        assert isinstance(result.exception, SystemExit), repr(result.exception)
        assert json.loads(result.output)["error_code"] == "RUN_ERROR"
        assert manifest.read_bytes() == before
        assert CliRunner().invoke(app, ["run", "report", tag, "--json"]).exit_code == 0
    finally:
        run_dir.chmod(0o755)
