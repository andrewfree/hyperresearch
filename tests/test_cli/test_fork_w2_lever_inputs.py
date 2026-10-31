import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.runs import init_run


@pytest.mark.parametrize("body", [b"[]", b"null", b'{"levers": ["teach"]}', b'{"levers": "teach"}', b"\xff"])
@pytest.mark.parametrize("command", [["set", "register=teach"], ["render"]])
def test_invalid_decomposition_returns_lever_error(tmp_vault, monkeypatch, body, command):
    tag = "input-aaaaaa"
    init_run(tmp_vault, tag)
    decomposition = tmp_vault.run_dir(tag) / "prompt-decomposition.json"
    decomposition.write_bytes(body)
    monkeypatch.chdir(tmp_vault.root)
    result = CliRunner().invoke(app, ["levers", command[0], tag, *command[1:], "--json"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert json.loads(result.output)["error_code"] == "LEVER_ERROR"
    assert decomposition.read_bytes() == body
    assert not (tmp_vault.run_dir(tag) / "shims").exists()
