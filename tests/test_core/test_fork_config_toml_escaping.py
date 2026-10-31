"""config.toml must stay parseable whatever text a string setting holds.

`VaultConfig.save` wrapped every string in bare double quotes, so a vault name
like `The "Deep" Lab` or a Windows path like `C:\\Users\\me` wrote a file
tomllib cannot read. Every command loads the config first, so one such value
locked the user out of every command, including the `config set` that would
undo it. Strings are now written as escaped TOML basic strings.
"""

from __future__ import annotations

import json
import tomllib

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.config import VaultConfig

runner = CliRunner()

AWKWARD = [
    'The "Deep" Lab',
    "C:\\Users\\me",
    "tab\there",
    "line\nbreak",
    "bell\x07and\x7fdel",
    "caf\u00e9 \U0001f9ea",
]


@pytest.fixture(autouse=True)
def _no_browser_setup(monkeypatch):
    # install probes for crawl4ai and may launch or install Chromium.
    monkeypatch.setattr(
        "hyperresearch.cli.install._setup_crawl4ai", lambda vault: "not_installed"
    )


@pytest.mark.parametrize("value", AWKWARD)
def test_string_settings_round_trip(tmp_path, value):
    path = tmp_path / "config.toml"
    config = VaultConfig(
        name=value,
        default_status=value,
        research_dir=value,
        web_provider=value,
        web_profile=value,
        pipeline_profile=value,
        exclude_patterns=[value, "plain/*"],
        index_pages=[value],
    )

    config.save(path)

    tomllib.loads(path.read_text(encoding="utf-8"))
    loaded = VaultConfig.load(path)
    assert loaded.name == value
    assert loaded.default_status == value
    assert loaded.research_dir == value
    assert loaded.web_provider == value
    assert loaded.web_profile == value
    assert loaded.pipeline_profile == value
    assert loaded.exclude_patterns == [value, "plain/*"]
    assert loaded.index_pages == [value]


def test_section_strings_and_profile_overlays_round_trip(tmp_path):
    from hyperresearch.core.config import EmbeddingSettings, ScholarSettings

    path = tmp_path / "config.toml"
    overlays = {
        "my gear": {"extends": 'f"ull', "models": {"fetcher": "a\\b"}},
        "plain": {"source_min": 60},
    }
    config = VaultConfig(
        embeddings=EmbeddingSettings(model='m"1'),
        scholar=ScholarSettings(contact_email="me\\@example.org"),
        profile_overlays=overlays,
    )

    config.save(path)

    loaded = VaultConfig.load(path)
    assert loaded.embeddings.model == 'm"1'
    assert loaded.scholar.contact_email == "me\\@example.org"
    assert loaded.profile_overlays == overlays


def test_install_with_a_quoted_vault_name(tmp_path, monkeypatch):
    root = tmp_path / "lab"
    root.mkdir()
    monkeypatch.chdir(root)

    result = runner.invoke(app, ["install", str(root), "--name", 'The "Deep" Lab', "--json"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["ok"] is True
    assert VaultConfig.load(root / ".hyperresearch" / "config.toml").name == 'The "Deep" Lab'

    status = runner.invoke(app, ["status", "--json"])
    assert status.exit_code == 0, status.output


def test_config_set_a_backslash_value_keeps_the_vault_usable(tmp_vault, monkeypatch):
    monkeypatch.chdir(tmp_vault.root)

    result = runner.invoke(app, ["config", "set", "vault.name", "C:\\Users\\me", "--json"])
    assert result.exit_code == 0, result.output

    got = runner.invoke(app, ["config", "get", "vault.name", "--json"])
    assert got.exit_code == 0, got.output
    assert json.loads(got.stdout)["data"]["value"] == "C:\\Users\\me"
    assert runner.invoke(app, ["status", "--json"]).exit_code == 0
