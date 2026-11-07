"""Unreadable vault configs produce actionable errors at each public boundary."""

from __future__ import annotations

import asyncio
import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()
COMMANDS = [
    ["status"], ["search", "foo"], ["note", "list"], ["config", "show"],
    ["sync"], ["config", "set", "vault.name", "Fixed"],
    ["profile", "show", "full"], ["profile", "validate"],
    ["install", ".", "--steps-only"], ["run", "init", "test-run"],
]
BAD_CONFIGS = [
    pytest.param(b"[viewer\nallow_remote_images = true\n", "line 1, column 8", id="toml"),
    pytest.param(b"# comment\n\xff", "UTF-8", id="utf8"),
    pytest.param(b"vault = 1\n", "[vault] must be a table", id="section"),
]


def assert_message(message, config_path, detail):
    assert str(config_path) in message
    assert detail in message
    assert "fix" in message.lower() and "by hand" in message
    assert "config set" in message and "cannot" in message
    assert "Traceback" not in message


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("raw,detail", BAD_CONFIGS)
@pytest.mark.parametrize("mode", [[], ["--json"], ["-j"]], ids=["human", "json", "short-json"])
def test_invalid_config_cli(tmp_vault, monkeypatch, command, raw, detail, mode):
    monkeypatch.chdir(tmp_vault.root)
    tmp_vault.config_path.write_bytes(raw)

    result = runner.invoke(app, [*command, *mode])

    assert result.exit_code == 1, result.output
    if mode:
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert payload["error_code"] == "CONFIG_INVALID"
        assert result.stderr == ""
        message = payload["error"]
    else:
        assert len(result.output.splitlines()) == 1, result.output
        message = result.output
    assert_message(message, tmp_vault.config_path, detail)
    assert tmp_vault.config_path.read_bytes() == raw


@pytest.mark.parametrize("raw,detail", BAD_CONFIGS)
@pytest.mark.parametrize("tool,args", [("vault_status", {}), ("search_notes", {"query": "foo"})])
def test_mcp_protocol_reports_invalid_config_and_recovers(tmp_vault, monkeypatch, raw, detail, tool, args):
    from mcp import types

    from hyperresearch.mcp import server as mcp

    monkeypatch.chdir(tmp_vault.root)
    monkeypatch.setattr(mcp, "_vault", None)
    original = tmp_vault.config_path.read_bytes()
    tmp_vault.config_path.write_bytes(raw)

    async def call():
        handler = mcp.server._mcp_server.request_handlers[types.CallToolRequest]
        response = await handler(types.CallToolRequest(
            method="tools/call", params=types.CallToolRequestParams(name=tool, arguments=args),
        ))
        return response.root

    result = asyncio.run(call())
    assert result.isError is True
    assert_message(result.content[0].text, tmp_vault.config_path, detail)
    tmp_vault.config_path.write_bytes(original)
    assert asyncio.run(call()).isError is False


@pytest.mark.parametrize("raw,detail", BAD_CONFIGS)
@pytest.mark.parametrize("platform", ["claude", "codex"])
def test_hook_install_refuses_invalid_config(tmp_vault, raw, detail, platform):
    from hyperresearch.core.hooks import HookRefusal, install_hooks

    tmp_vault.config_path.write_bytes(raw)
    actions = install_hooks(tmp_vault.root, platform=platform)
    assert len(actions) == 1
    assert isinstance(actions[0], HookRefusal)
    assert_message(actions[0], tmp_vault.config_path, detail)
    assert not (tmp_vault.root / ".claude").exists()
    assert not (tmp_vault.root / ".codex").exists()
    assert tmp_vault.config_path.read_bytes() == raw


def test_json_word_after_option_terminator_is_a_human_search(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    tmp_vault.config_path.write_bytes(b"[viewer\n")
    result = runner.invoke(app, ["search", "--", "--json"])
    assert result.exit_code == 1
    assert result.output.startswith("Error:")


def test_valid_config_cli_still_works(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)
    result = runner.invoke(app, ["status", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"] is True
