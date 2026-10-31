"""'hyperresearch serve' reports an unusable port as a one-line error, not a traceback."""

from __future__ import annotations

import socket

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def vault_cwd(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    return tmp_vault


def test_busy_port_prints_one_line_error(vault_cwd):
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen(1)
        port = holder.getsockname()[1]
        result = runner.invoke(app, ["serve", "--port", str(port)])

    # An uncaught OSError also exits 1, so the exception type is what tells them apart.
    assert isinstance(result.exception, SystemExit), result.exception
    assert result.exit_code == 1
    assert f"port {port} is already in use" in result.output


@pytest.mark.parametrize("port", ["70000", "-1"])
def test_out_of_range_port_is_a_usage_error(vault_cwd, port):
    result = runner.invoke(app, ["serve", "--port", port])

    assert isinstance(result.exception, SystemExit), result.exception
    assert result.exit_code == 2
    assert "65535" in result.output
