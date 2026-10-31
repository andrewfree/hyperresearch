"""One malformed run manifest must not break every other run.

list_runs promised to tolerate corrupt manifests but only caught
JSONDecodeError. A manifest that parsed to something other than an object
(`null`, a list), was not UTF-8, or carried a non-string started_at raised
from list_runs itself, so `run list`, `run status`, `run report --all` and the
Codex Stop gate (which swallows the exception and prints nothing) all failed
for every run in the vault. load_manifest had the same blind spot, so
`run status <bad-run>` crashed with a traceback instead of a RUN_ERROR.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core import codex
from hyperresearch.core.runs import RunError, init_run, list_runs, load_manifest, manifest_path

runner = CliRunner()

OLD, LIVE = "old-aaaaaa", "live-bbbbbb"

BAD_MANIFESTS = {
    "json-null": b"null\n",
    "json-list": b"[1, 2]\n",
    "json-string": b'"run"\n',
    "not-utf8": b"\xff\xfe",
    "missing-keys": b"{}\n",
    "steps-not-object": json.dumps(
        {"vault_tag": OLD, "profile": "full", "status": "running", "steps": [], "spend": {}}
    ).encode(),
}


@pytest.fixture
def two_runs(tmp_vault):
    init_run(tmp_vault, OLD)
    init_run(tmp_vault, LIVE)
    # The live run is the newest one regardless of clock resolution.
    old = load_manifest(tmp_vault, OLD)
    old["started_at"] = "2026-01-01T00:00:00+00:00"
    manifest_path(tmp_vault, OLD).write_text(json.dumps(old), encoding="utf-8")
    return tmp_vault


def _corrupt(vault, content: bytes) -> None:
    manifest_path(vault, OLD).write_bytes(content)


@pytest.mark.parametrize("content", BAD_MANIFESTS.values(), ids=BAD_MANIFESTS.keys())
def test_list_runs_marks_the_bad_manifest_and_keeps_the_rest(two_runs, content):
    _corrupt(two_runs, content)
    runs = list_runs(two_runs)
    assert [r["vault_tag"] for r in runs] == [LIVE, OLD]
    assert runs[1] == {"vault_tag": OLD, "status": "corrupt-manifest"}


@pytest.mark.parametrize("content", BAD_MANIFESTS.values(), ids=BAD_MANIFESTS.keys())
def test_load_manifest_raises_run_error(two_runs, content):
    _corrupt(two_runs, content)
    with pytest.raises(RunError, match=f"corrupt manifest for run '{OLD}'"):
        load_manifest(two_runs, OLD)


@pytest.mark.parametrize("content", BAD_MANIFESTS.values(), ids=BAD_MANIFESTS.keys())
def test_stop_gate_still_blocks_for_the_live_run(two_runs, content):
    assert codex.stop_gate_decision(two_runs)["reason"].startswith(f"{LIVE} is at step 1")
    _corrupt(two_runs, content)
    decision = codex.stop_gate_decision(two_runs)
    assert decision is not None
    assert decision["reason"].startswith(f"{LIVE} is at step 1")


@pytest.mark.parametrize("started_at", [None, 7, ["2099"]], ids=["null", "int", "list"])
def test_non_string_started_at_sorts_last_instead_of_crashing(two_runs, started_at):
    old = load_manifest(two_runs, OLD)
    old["started_at"] = started_at
    manifest_path(two_runs, OLD).write_text(json.dumps(old), encoding="utf-8")
    assert [r["vault_tag"] for r in list_runs(two_runs)] == [LIVE, OLD]
    assert codex.stop_gate_decision(two_runs)["reason"].startswith(f"{LIVE} is at step 1")


@pytest.mark.parametrize("content", BAD_MANIFESTS.values(), ids=BAD_MANIFESTS.keys())
def test_run_commands_keep_working_for_the_other_runs(two_runs, content, monkeypatch):
    monkeypatch.chdir(two_runs.root)
    _corrupt(two_runs, content)

    listed = runner.invoke(app, ["run", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    rows = json.loads(listed.stdout)["data"]["runs"]
    assert [(r["vault_tag"], r["status"]) for r in rows] == [
        (LIVE, "running"),
        (OLD, "corrupt-manifest"),
    ]

    status = runner.invoke(app, ["run", "status", "--json"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout)["data"]["vault_tag"] == LIVE

    report = runner.invoke(app, ["run", "report", "--all", "--json"])
    assert report.exit_code == 0, report.output
    assert [r["vault_tag"] for r in json.loads(report.stdout)["data"]["by_run"]] == [LIVE]


@pytest.mark.parametrize("command", ["status", "resume", "report", "step"])
@pytest.mark.parametrize("content", BAD_MANIFESTS.values(), ids=BAD_MANIFESTS.keys())
def test_the_bad_run_itself_gets_a_run_error_envelope(two_runs, content, command, monkeypatch):
    monkeypatch.chdir(two_runs.root)
    _corrupt(two_runs, content)
    args = ["run", command, OLD] + (["2", "--status", "running"] if command == "step" else [])
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_code"] == "RUN_ERROR"
    assert f"corrupt manifest for run '{OLD}'" in payload["error"]


def test_report_all_tolerates_a_spend_block_missing_counters(two_runs, monkeypatch):
    monkeypatch.chdir(two_runs.root)
    old = load_manifest(two_runs, OLD)
    old["spend"] = {}
    manifest_path(two_runs, OLD).write_text(json.dumps(old), encoding="utf-8")
    report = runner.invoke(app, ["run", "report", "--all", "--json"])
    assert report.exit_code == 0, report.output
    data = json.loads(report.stdout)["data"]
    assert data["runs"] == 2
    assert data["total_sources"] == 0
