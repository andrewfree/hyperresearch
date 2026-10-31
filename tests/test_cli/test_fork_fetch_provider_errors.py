"""A provider that cannot load is an error envelope, not a traceback.

get_provider raises ValueError for an unknown name, RuntimeError for a
missing API key and ImportError for a missing extra. fetch, fetch-batch and
research called it outside any handler, so --json callers got an empty
stdout and a Rich traceback on stderr.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()

COMMANDS = {
    "fetch": ["fetch", "https://site.example.org/a"],
    "fetch-batch": ["fetch-batch", "https://site.example.org/a"],
    "research": ["research", "estuary sediments"],
}


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    assert runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Providers"]).exit_code == 0
    os.chdir(tmp_path / "kb")
    for key in ("EXA_API_KEY", "SERPLY_API_KEY", "TAVILY_API_KEY", "PARALLEL_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    return tmp_path / "kb"


def _envelope(args: list[str]) -> dict:
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 1, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    return envelope


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_an_unknown_provider_is_a_bad_provider_error(vault_dir: Path, command: str):
    envelope = _envelope([*COMMANDS[command], "--provider", "bogus"])
    assert envelope["error_code"] == "BAD_PROVIDER"
    assert "Unknown web provider: 'bogus'" in envelope["error"]


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_a_provider_without_its_key_is_unavailable(vault_dir: Path, command: str):
    envelope = _envelope([*COMMANDS[command], "--provider", "serply"])
    assert envelope["error_code"] == "PROVIDER_UNAVAILABLE"
    assert "SERPLY_API_KEY" in envelope["error"]


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_a_missing_extra_is_unavailable(vault_dir: Path, monkeypatch, command: str):
    def missing_extra(*args, **kwargs):
        raise ImportError('tavily provider requires: pip install "hyperresearch[tavily]"')

    monkeypatch.setattr("hyperresearch.web.base.get_provider", missing_extra)
    envelope = _envelope(COMMANDS[command])
    assert envelope["error_code"] == "PROVIDER_UNAVAILABLE"
    assert "hyperresearch[tavily]" in envelope["error"]


def test_the_configured_provider_gets_the_same_envelope(vault_dir: Path):
    cfg = vault_dir / ".hyperresearch" / "config.toml"
    text = cfg.read_text(encoding="utf-8")
    assert 'provider = "builtin"' in text
    cfg.write_text(text.replace('provider = "builtin"', 'provider = "bogus"', 1), encoding="utf-8")
    envelope = _envelope(COMMANDS["fetch"])
    assert envelope["error_code"] == "BAD_PROVIDER"


@pytest.mark.parametrize("command", sorted(COMMANDS))
def test_human_mode_prints_the_reason_without_a_traceback(vault_dir: Path, command: str):
    result = runner.invoke(app, [*COMMANDS[command], "--provider", "bogus"])
    assert result.exit_code == 1
    assert isinstance(result.exception, SystemExit)
    assert "Unknown web provider" in result.output
