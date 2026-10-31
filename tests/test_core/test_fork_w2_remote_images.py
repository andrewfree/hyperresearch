"""Viewer image loading is local by default and never sends referrers."""

from dataclasses import replace
from html.parser import HTMLParser

import pytest

from hyperresearch.core.config import VaultConfig
from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.serve.renderer import render_markdown
from hyperresearch.serve.server import HyperresearchHandler


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.mark.parametrize("url", [
    "https://example.com/pixel.png",
    "http://example.com/pixel.png",
    "HTTPS://example.com/pixel.png",
    "//example.com/pixel.png",
    "\\\\example.com/pixel.png",
    "h\tttps://example.com/pixel.png",
])
def test_remote_images_are_links_by_default(url):
    out = render_markdown(f'![a "picture" & caption]({url})')
    tags = Tags(out).tags

    assert not any(tag == "img" for tag, _ in tags)
    assert any(tag == "a" for tag, _ in tags)
    assert "a &quot;picture&quot; &amp; caption</a>" in out


@pytest.mark.parametrize("url", ["local.png", "/assets/image.png", "data:image/png;base64,AAAA"])
def test_local_and_data_images_have_no_referrer(url):
    tags = Tags(render_markdown(f"![picture]({url})")).tags
    images = [attrs for tag, attrs in tags if tag == "img"]

    assert images == [{"src": url, "alt": "picture", "referrerpolicy": "no-referrer"}]


def test_remote_images_can_be_allowed_explicitly():
    tags = Tags(render_markdown("![picture](https://example.com/x.png)", allow_remote_images=True)).tags
    assert [attrs for tag, attrs in tags if tag == "img"] == [
        {"src": "https://example.com/x.png", "alt": "picture", "referrerpolicy": "no-referrer"},
    ]


def test_viewer_setting_defaults_off_and_round_trips(tmp_path):
    config_path = tmp_path / "config.toml"
    config = VaultConfig.load(config_path)
    assert config.viewer.allow_remote_images is False
    config.viewer = replace(config.viewer, allow_remote_images=True)
    config.save(config_path)

    assert "[viewer]" in config_path.read_text()
    assert VaultConfig.load(config_path).viewer.allow_remote_images is True


@pytest.mark.parametrize("allow_remote", [False, True])
def test_note_handler_uses_viewer_image_setting(tmp_vault, allow_remote):
    write_note(tmp_vault.notes_dir, "Fetched", body="![pixel](https://example.com/pixel.png)")
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    tmp_vault.config.viewer = replace(tmp_vault.config.viewer, allow_remote_images=allow_remote)
    tmp_vault.config.save(tmp_vault.config_path)
    handler = object.__new__(HyperresearchHandler)
    handler.vault = tmp_vault
    handler._db = tmp_vault.db
    responses = []
    handler._send = lambda *args: responses.append(args)

    handler._serve_note("fetched")

    tags = Tags(responses[0][1]).tags
    assert any(tag == "img" for tag, _ in tags) is allow_remote
