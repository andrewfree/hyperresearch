import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.runs import init_run


@pytest.mark.parametrize("spend", [{}, {"estimated_usd": 1.25}, {"sources_fetched": 3}])
def test_single_report_with_partial_spend(tmp_vault, monkeypatch, spend):
    tag = "partial-aaaaaa"
    manifest = init_run(tmp_vault, tag)
    manifest["spend"] = spend
    (tmp_vault.run_dir(tag) / "run.json").write_text(json.dumps(manifest))
    monkeypatch.chdir(tmp_vault.root)
    result = CliRunner().invoke(app, ["run", "report", tag])
    assert result.exit_code == 0, repr(result.exception)
    assert f"~${spend.get('estimated_usd', 0.0)}" in result.output
    assert f"{spend.get('sources_fetched', 0)} sources" in result.output
    assert "0 agents | 0 notes" in result.output
