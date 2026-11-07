"""Config decoding fails with one typed error and leaves the file untouched."""

import pytest

from hyperresearch.core.config import VaultConfig


@pytest.mark.parametrize("raw,detail", [
    (b"[viewer\nallow_remote_images = true\n", "line 1, column 8"),
    (b"[viewer", "line 1, column 8"),
    (b"# caf\xc3\xa9\n\xff", "line 2, column 1"),
])
def test_load_raises_typed_config_error(tmp_path, raw, detail):
    from hyperresearch.core.config import ConfigInvalidError

    config_path = tmp_path / "config.toml"
    config_path.write_bytes(raw)
    with pytest.raises(ConfigInvalidError) as caught:
        VaultConfig.load(config_path)
    assert str(config_path) in str(caught.value)
    assert detail in str(caught.value)
    assert "by hand" in str(caught.value)
    assert "config set" in str(caught.value)
    assert config_path.read_bytes() == raw


@pytest.mark.parametrize("section", [
    "vault", "sync", "index", "search", "web", "pipeline", "fetch", "junk", "assets",
    "viewer", "dedup", "lint", "ranking", "embeddings", "chrome", "scholar", "profile",
])
def test_load_refuses_non_table_sections(tmp_path, section):
    from hyperresearch.core.config import ConfigInvalidError

    config_path = tmp_path / "config.toml"
    config_path.write_text(f"{section} = 1\n", encoding="utf-8")
    with pytest.raises(ConfigInvalidError, match=rf"\[{section}\] must be a table"):
        VaultConfig.load(config_path)


def test_missing_config_still_means_defaults(tmp_path):
    assert VaultConfig.load(tmp_path / "missing.toml") == VaultConfig()


def test_valid_config_still_loads(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[vault]\nname = "My Vault"\n[viewer]\nallow_remote_images = true\n', encoding="utf-8",
    )
    config = VaultConfig.load(config_path)
    assert config.name == "My Vault"
    assert config.viewer.allow_remote_images is True


def test_empty_config_still_means_defaults(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(b"")
    assert VaultConfig.load(config_path) == VaultConfig()
