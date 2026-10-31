import errno
import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core import runs


@pytest.mark.parametrize("errnum", [errno.ENOLCK, errno.ENOTSUP])
@pytest.mark.parametrize("command", [["step", "1", "--status", "running"], ["event", "--type", "spawn"], ["spend", "--usd", "1"]])
def test_unsupported_manifest_lock_envelope(tmp_vault, monkeypatch, errnum, command):
    tag = "lock-aaaaaa"
    runs.init_run(tmp_vault, tag)
    before = (tmp_vault.run_dir(tag) / "run.json").read_bytes()
    real_lock = runs._lock_file

    def unsupported(fd):
        raise OSError(errnum, "filesystem does not support flock")

    monkeypatch.setattr(runs, "_lock_file", unsupported)
    monkeypatch.chdir(tmp_vault.root)
    result = CliRunner().invoke(app, ["run", command[0], tag, *command[1:], "--json"])
    assert result.exit_code == 1
    assert json.loads(result.output)["error_code"] == "RUN_ERROR"
    assert "cannot lock run" in json.loads(result.output)["error"]
    assert (tmp_vault.run_dir(tag) / "run.json").read_bytes() == before
    monkeypatch.setattr(runs, "_lock_file", real_lock)
    runs.set_status(tmp_vault, tag, "paused")
