"""`search --min-inbound 0` keeps notes that have no inbound links.

The filter was `id IN (targets GROUP BY target_id HAVING COUNT(*) >= ?)`, and a
note with no inbound link is never a target, so 0 dropped it instead of being
a no-op.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app

runner = CliRunner()


@pytest.fixture
def linked_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root), "--name", "Inbound"]).exit_code == 0
    monkeypatch.chdir(root)
    for title, body in [("Target", "zebra"), ("Linker", "See [[target]]."), ("Alone", "nothing")]:
        result = runner.invoke(app, ["note", "new", title, "-b", body, "--json"])
        assert result.exit_code == 0, result.output
    return root


def _ids(*flags: str) -> set[str]:
    result = runner.invoke(app, ["search", *flags, "-j", "--no-body"])
    assert result.exit_code == 0, result.output
    return {r["id"] for r in json.loads(result.stdout)["data"]["results"]}


@pytest.mark.parametrize("value", ["0", "-1"])
def test_min_inbound_zero_or_less_keeps_every_note(linked_vault, value):
    assert _ids("--type", "note", "--min-inbound", value) == {"alone", "linker", "target"}


def test_min_inbound_zero_alone_is_still_a_filter(linked_vault):
    # As the only option it still makes a filter-only listing, not a query error.
    assert _ids("--min-inbound", "0") == {"alone", "linker", "target"}


def test_min_inbound_with_a_text_query(linked_vault):
    assert _ids("zebra", "--min-inbound", "0") == {"target"}
    assert _ids("nothing", "--min-inbound", "0") == {"alone"}
    assert _ids("nothing", "--min-inbound", "1") == set()


def test_min_inbound_one_still_filters(linked_vault):
    assert _ids("--type", "note", "--min-inbound", "1") == {"target"}
    assert _ids("--type", "note", "--min-inbound", "2") == set()
