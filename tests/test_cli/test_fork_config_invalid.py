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
    ["claims", "list"],
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


@pytest.mark.parametrize("args,json_mode", [
    (["note", "new", "Example", "--body", "--json"], False),
    (["note", "new", "Example", "--body", "-j"], False),
    (["note", "new", "Example", "--body", "--", "--json"], True),
    (["note", "new", "Example", "-je"], True),
    (["note", "new", "--json", "Example"], True),
    (["search", "--json", "foo"], True),
    (["search", "a --json b"], False),
    (["note", "new", "a --json b"], False),
    (["note", "new", "--", "--json"], False),
])
def test_config_error_uses_parsed_json_option(tmp_vault, monkeypatch, args, json_mode):
    monkeypatch.chdir(tmp_vault.root)
    tmp_vault.config_path.write_bytes(b"[viewer\n")
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    if json_mode:
        assert json.loads(result.stdout)["error_code"] == "CONFIG_INVALID"
        assert result.stderr == ""
    else:
        assert result.stdout == ""
        assert result.stderr.startswith("Error: Invalid config ")
    assert "Traceback" not in result.output


@pytest.mark.parametrize("args", [["status"], ["status", "--json"]])
def test_config_handler_preserves_unrelated_exception(tmp_vault, monkeypatch, args):
    from hyperresearch.core.vault import Vault

    def broken_discover(*args, **kwargs):
        raise RuntimeError("unrelated implementation bug")

    monkeypatch.setattr(Vault, "discover", broken_discover)
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert isinstance(result.exception, RuntimeError)
    assert str(result.exception) == "unrelated implementation bug"
    assert result.output == ""


@pytest.mark.parametrize("contents", [None, b"", b'[vault]\nname = "Valid"\n'])
def test_default_and_valid_configs_work_at_discovery(tmp_vault, monkeypatch, contents):
    monkeypatch.chdir(tmp_vault.root)
    if contents is None:
        tmp_vault.config_path.unlink()
    else:
        tmp_vault.config_path.write_bytes(contents)
    for args in (["status", "--json"], ["claims", "list", "--json"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["ok"] is True
