import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core import runs


@pytest.mark.parametrize("state,interleave", [("paused", "abort"), ("blocked", "abort"), ("blocked", "resume")])
def test_resume_rechecks_status_after_concurrent_change(tmp_vault, monkeypatch, state, interleave):
    tag = "resume-aaaaaa"
    runs.init_run(tmp_vault, tag)
    runs.set_status(tmp_vault, tag, state, blocked_on="max_sources" if state == "blocked" else None)
    original_load = runs.load_manifest
    changed = False

    def load_with_concurrent_change(vault, vault_tag):
        nonlocal changed
        manifest = original_load(vault, vault_tag)
        if not changed:
            changed = True
            if interleave == "abort":
                runs.set_status(vault, vault_tag, "aborted")
            else:
                runs.clear_count_block(vault, vault_tag)
        return manifest

    monkeypatch.setattr(runs, "load_manifest", load_with_concurrent_change)
    monkeypatch.chdir(tmp_vault.root)
    result = CliRunner().invoke(app, ["run", "resume", tag, "--json"])
    assert result.exit_code == 0, result.output
    final = original_load(tmp_vault, tag)
    assert final["status"] == ("aborted" if interleave == "abort" else "running")
    assert final["counts_force_cleared"] == (0 if interleave == "abort" else 1)


@pytest.mark.parametrize("status", ["running", "paused"])
def test_resume_readonly_vault(tmp_vault, monkeypatch, status):
    tag = "readonly-aaaaaa"
    runs.init_run(tmp_vault, tag)
    runs.set_status(tmp_vault, tag, status)
    run_dir = tmp_vault.run_dir(tag)
    lock = run_dir / runs.LOCK_NAME
    lock.chmod(0o444)
    run_dir.chmod(0o555)
    monkeypatch.chdir(tmp_vault.root)
    try:
        result = CliRunner().invoke(app, ["run", "resume", tag, "--json"])
        data = json.loads(result.output)
        if status == "running":
            assert result.exit_code == 0, result.output
        else:
            assert result.exit_code == 1
            assert data["error_code"] == "RUN_ERROR"
            assert "cannot lock run" in data["error"]
    finally:
        run_dir.chmod(0o755)
        lock.chmod(0o644)


def test_abort_queued_during_resume_wins(tmp_vault, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    tag = "queued-aaaaaa"
    runs.init_run(tmp_vault, tag)
    runs.set_status(tmp_vault, tag, "paused")
    real_set_status = runs.set_status
    abort_started = threading.Event()
    abort_finished = threading.Event()

    def abort():
        abort_started.set()
        real_set_status(tmp_vault, tag, "aborted")
        abort_finished.set()

    with ThreadPoolExecutor(max_workers=1) as pool:
        queued = []

        def set_while_abort_queues(vault, vault_tag, status):
            queued.append(pool.submit(abort))
            assert abort_started.wait(5)
            abort_finished.wait(0.1)
            return real_set_status(vault, vault_tag, status)

        monkeypatch.setattr(runs, "set_status", set_while_abort_queues)
        runs.resume_run(tmp_vault, tag)
        for future in queued:
            future.result(timeout=5)
    assert runs.load_manifest(tmp_vault, tag)["status"] == "aborted"
