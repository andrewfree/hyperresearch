"""fetch-batch --save-assets downloads images under the vault's [fetch] limits.

The batch call to _save_assets passed only image_timeout_s, so images were
downloaded with the default max_image_bytes and an empty allow_private_hosts:
an allowlisted private host was refused, and a raised size cap ignored, even
though `fetch --save-assets` honored both. Offline: safe_get is stubbed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.web.base import WebResult

runner = CliRunner()

IMAGE_URL = "http://10.0.0.5/figures/plot.png"


class _PageWithImageProvider:
    name = "fake-images"

    def fetch(self, url: str) -> WebResult:
        return WebResult(
            url=url,
            title=f"Page {url[-1]}",
            content="A page about estuaries with a figure in it. " * 20,
            media=[{"src": IMAGE_URL, "alt": "plot", "score": 5}],
        )


class _Resp:
    def __init__(self):
        self.content = b"\x89PNG" + b"0" * 60_000
        self.headers = {"content-type": "image/png"}


@pytest.fixture
def vault_dir(tmp_path: Path, monkeypatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Batch Assets"])
    assert result.exit_code == 0
    root = tmp_path / "kb"
    cfg = root / ".hyperresearch" / "config.toml"
    cfg.write_text(
        cfg.read_text(encoding="utf-8")
        .replace("max_image_bytes = 2097152", "max_image_bytes = 4194304")
        .replace("allow_private_hosts = []", 'allow_private_hosts = ["10.0.0.5"]'),
        encoding="utf-8",
    )
    os.chdir(root)
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _PageWithImageProvider()
    )
    return root


def test_batch_image_downloads_use_the_vault_fetch_limits(vault_dir: Path, monkeypatch):
    calls: list[dict] = []

    def fake_safe_get(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return _Resp()

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)

    single = runner.invoke(app, ["fetch", "https://a.example.org/p1", "--save-assets", "--json"])
    assert single.exit_code == 0, single.output
    batch = runner.invoke(
        app, ["fetch-batch", "https://a.example.org/p2", "--save-assets", "--json"]
    )
    assert batch.exit_code == 0, batch.output

    assert [c["url"] for c in calls] == [IMAGE_URL, IMAGE_URL]
    for call in calls:
        assert call["max_bytes"] == 4194304
        assert tuple(call["allow_private_hosts"]) == ("10.0.0.5",)

    note_id = json.loads(batch.stdout)["data"]["notes_created"][0]["note_id"]
    listed = runner.invoke(app, ["assets", "list", "--note", note_id, "--json"])
    assert [a["type"] for a in json.loads(listed.stdout)["data"]] == ["image"]
