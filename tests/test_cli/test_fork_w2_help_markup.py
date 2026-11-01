"""Render the command tree's help, preserving documented wiki-link syntax."""

import re

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


def _commands(command, prefix=()):
    yield prefix, command
    for name, child in getattr(command, "commands", {}).items():
        yield from _commands(child, (*prefix, name))


@pytest.mark.parametrize("args,command", list(_commands(get_command(app))))
def test_command_help_preserves_wikilinks(args, command):
    result = runner.invoke(app, [*args, "--help"], env={"COLUMNS": "400"})
    assert result.exit_code == 0, result.output
    sources = [command.help or "", *(getattr(p, "help", "") or "" for p in command.params)]
    expected = [link.replace("\\[", "[") for source in sources
                for link in re.findall(r"\[(?:\\)?\[[^\]]+\]\]", source)]
    for link in expected:
        assert link in result.output
        assert "[]" not in result.output
