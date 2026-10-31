"""`config set` on a numeric key must not write a value no command can load.

`config set search.boost_evergreen high` stored the raw string, `save` wrote it
bare (`boost_evergreen = high`), and every later command, including the
`config set` that would undo it, failed with a TOMLDecodeError. Numeric keys
are now parsed as numbers and a bad value is refused with nothing written, and
`save` itself refuses to write text that does not parse.
"""

from __future__ import annotations

import json
import tomllib

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.config import VaultConfig

runner = CliRunner()


@pytest.mark.parametrize("key", ["search.boost_evergreen", "search.penalize_deprecated"])
@pytest.mark.parametrize("bad", ["high", "", "1,5", "nan", "inf"])
def test_config_set_refuses_a_non_number_for_a_float_key(tmp_vault, monkeypatch, key, bad):
    monkeypatch.chdir(tmp_vault.root)
    before = tmp_vault.config_path.read_bytes()

    result = runner.invoke(app, ["config", "set", key, bad, "--json"])

    assert result.exit_code == 1, result.output
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error_code"] == "INVALID_VALUE"
    assert key in payload["error"]
    assert tmp_vault.config_path.read_bytes() == before
    assert runner.invoke(app, ["note", "list", "--json"]).exit_code == 0


def test_config_set_refusal_in_text_mode(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)

    result = runner.invoke(app, ["config", "set", "search.boost_evergreen", "high"])

    assert result.exit_code == 1
    assert "must be a number" in result.output


def test_config_set_stores_a_float_key_as_a_number(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)

    result = runner.invoke(app, ["config", "set", "search.boost_evergreen", "2.5", "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["data"]["value"] == 2.5
    data = tomllib.loads(tmp_vault.config_path.read_text(encoding="utf-8"))
    assert data["search"]["boost_evergreen"] == 2.5
    got = runner.invoke(app, ["config", "get", "search.boost_evergreen", "--json"])
    assert json.loads(got.stdout)["data"]["value"] == 2.5


def test_save_refuses_a_non_number_in_a_numeric_field(tmp_path):
    path = tmp_path / "config.toml"
    VaultConfig().save(path)
    before = path.read_bytes()

    config = VaultConfig()
    config.search_boost_evergreen = "high"
    with pytest.raises(ValueError):
        config.save(path)

    assert path.read_bytes() == before


def test_save_still_writes_a_numeric_string_as_a_number(tmp_path):
    # A hand-edited `boost_evergreen = "1.5"` loads as a string; saving has
    # always written it back as the bare number.
    path = tmp_path / "config.toml"
    config = VaultConfig()
    config.search_boost_evergreen = "1.5"
    config.search_default_limit = "30"

    config.save(path)

    loaded = VaultConfig.load(path)
    assert loaded.search_boost_evergreen == 1.5
    assert loaded.search_default_limit == 30


def test_save_refuses_a_value_toml_cannot_hold(tmp_path):
    from hyperresearch.core.config import EmbeddingSettings

    path = tmp_path / "config.toml"
    VaultConfig().save(path)
    before = path.read_bytes()

    # None has no TOML spelling; a section field holding one must not reach
    # the file as a bare `None`.
    config = VaultConfig(embeddings=EmbeddingSettings(model=None))
    with pytest.raises(ValueError):
        config.save(path)

    assert path.read_bytes() == before
