"""Config decoding fails with one typed error and leaves the file untouched."""

import sys

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


@pytest.mark.parametrize("kind", ["directory", "permission", "symlink-loop"])
def test_load_wraps_config_read_errors(tmp_path, kind, deny_file_reads):
    import errno
    import os

    from hyperresearch.core.config import ConfigInvalidError

    config_path = tmp_path / "config.toml"
    if kind == "directory":
        config_path.mkdir()
        expected_errno = errno.EACCES if sys.platform == "win32" else errno.EISDIR
    elif kind == "symlink-loop":
        config_path.symlink_to(config_path)
        # Measured with read_bytes on Windows 11, Python 3.11.17: EINVAL, no winerror.
        expected_errno = errno.EINVAL if sys.platform == "win32" else errno.ELOOP
    else:
        config_path.write_text("[vault]\n", encoding="utf-8")
        if sys.platform == "win32":
            # Windows chmod only controls writing, so model an ACL read denial.
            deny_file_reads(config_path)
        else:
            config_path.chmod(0)
        expected_errno = errno.EACCES
    try:
        with pytest.raises(ConfigInvalidError) as caught:
            VaultConfig.load(config_path)
        assert str(config_path) in str(caught.value)
        cause = caught.value.__cause__
        assert isinstance(cause, OSError)
        if sys.platform == "win32":
            # Windows file errors carry their own message, not the CRT errno text.
            assert cause.strerror in str(caught.value)
            assert cause.errno == expected_errno
        else:
            assert os.strerror(expected_errno) in str(caught.value)
            assert cause.errno == expected_errno
    finally:
        if kind == "permission":
            config_path.chmod(0o600)
    if kind == "directory":
        assert config_path.is_dir()
    elif kind == "symlink-loop":
        assert config_path.is_symlink()
    else:
        assert config_path.read_text(encoding="utf-8") == "[vault]\n"


def test_dangling_config_symlink_still_means_defaults(tmp_path):
    config_path = tmp_path / "config.toml"
    config_path.symlink_to(tmp_path / "missing.toml")
    assert VaultConfig.load(config_path) == VaultConfig()
    assert config_path.is_symlink()


def test_dangling_config_symlink_through_regular_file_still_means_defaults(tmp_path):
    shared = tmp_path / "shared"
    shared.write_text("regular file", encoding="utf-8")
    config_path = tmp_path / "config.toml"
    config_path.symlink_to(shared / "config.toml")
    assert not config_path.exists()
    assert VaultConfig.load(config_path) == VaultConfig()
    assert config_path.is_symlink()
    assert shared.read_text(encoding="utf-8") == "regular file"


@pytest.mark.parametrize("raw", [
    "[profile]\nmine = 3\n",
    "profile.mine = 1\n",
    'profile."my gear" = false\n',
])
def test_load_refuses_non_table_profile_entries(tmp_path, raw):
    from hyperresearch.core.config import ConfigInvalidError

    config_path = tmp_path / "config.toml"
    config_path.write_text(raw, encoding="utf-8")
    with pytest.raises(ConfigInvalidError) as caught:
        VaultConfig.load(config_path)
    assert str(config_path) in str(caught.value)
    key = 'profile."my gear"' if "my gear" in raw else "profile.mine"
    assert f"[{key}] must be a table" in str(caught.value)
    assert config_path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize("body,name,detail", [
    ("[profile.mine]\nsource_minn = 60\n", "mine", "invalid profile"),
    ("[profile.mine]\nsource_target = [80, 55]\n", "mine", "invalid profile"),
    ("[profile.mine]\n", "missing", "unknown profile"),
])
def test_profile_content_errors_still_raise_profile_error(tmp_path, body, name, detail):
    from hyperresearch.core.profiles import ProfileError, resolve_profile

    config_path = tmp_path / "config.toml"
    config_path.write_text(body, encoding="utf-8")
    assert "mine" in VaultConfig.load(config_path).profile_overlays
    with pytest.raises(ProfileError, match=detail):
        resolve_profile(name, config_path)
