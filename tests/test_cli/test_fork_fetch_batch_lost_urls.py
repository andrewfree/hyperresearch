"""Every fetch-batch input is accounted for: created, skipped or failed.

The crawl4ai batch lane logged and skipped a URL the SSRF gate refused, one
whose navigation failed (a redirect loop, an anti-bot verdict, a bad
certificate) and one whose final URL the gate refused, then returned only
the successes. fetch-batch could not learn about them, so 5 inputs came back
as 2 notes and an empty failed_urls. fetch_many now reports what it lost, and
fetch-batch fails any input a provider answered neither way. Offline: the
browser is a fake crawler and only IP literals are resolved.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path

import pytest
from typer.testing import CliRunner

import hyperresearch.web.crawl4ai_provider as c4
from hyperresearch.cli import app
from hyperresearch.core.config import FetchSettings, JunkGates
from hyperresearch.web.base import BatchResults, WebResult

runner = CliRunner()

TEXT = "River sediments settle in estuaries over long periods of time. " * 20
CERT_ERROR = "Page.goto: net::ERR_CERT_AUTHORITY_INVALID at https://8.8.8.8/self-signed"


def _run(coro):
    """Run ``coro`` on a fresh thread: a prior test can leave this thread's
    event loop marked as running (see tests/test_web/test_fetch_many_gate.py)."""
    box: dict = {}

    def target() -> None:
        try:
            box["result"] = asyncio.run(coro)
        except Exception as exc:
            box["error"] = exc

    thread = threading.Thread(target=target)
    thread.start()
    thread.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


class _CR:
    """Stand-in for a crawl4ai result."""

    def __init__(self, url: str, *, error: str = "", final_url: str | None = None):
        self.success = not error
        self.url = url
        self.redirected_url = final_url or url
        self.error_message = error
        self.markdown = TEXT if not error else ""
        self.metadata = {"title": "T"}
        self.media = {}
        self.links = {}
        self.screenshot = None
        self.html = "<html></html>"


class _FakeCrawler:
    def __init__(self, results: dict):
        self._results = results

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def arun_many(self, urls, config):
        return [self._results[u] for u in reversed(urls)]


GOOD = "http://8.8.8.8/good"
LOOP = "http://8.8.8.8/loop"
EMPTY = "http://8.8.8.8/empty"
CERT = "https://8.8.8.8/self-signed"
ESCAPES = "http://8.8.8.8/escapes"
PRIVATE = "http://10.1.2.3/z"
MALFORMED = "http://[::1/broken"


def _provider(monkeypatch) -> c4.Crawl4AIProvider:
    results = {
        GOOD: _CR(GOOD),
        LOOP: _CR(LOOP, error="Page.goto: net::ERR_TOO_MANY_REDIRECTS at http://8.8.8.8/loop"),
        EMPTY: _CR(EMPTY, error="Blocked by anti-bot protection: Near-empty content (59 bytes)"),
        CERT: _CR(CERT, error=CERT_ERROR),
        ESCAPES: _CR(ESCAPES, final_url="http://127.0.0.1/secret"),
    }
    inst = c4.Crawl4AIProvider.__new__(c4.Crawl4AIProvider)
    inst._settings = FetchSettings()
    inst._gates = JunkGates()
    inst._run_config = object()
    inst._headless = True
    inst._data_dir = None
    monkeypatch.setattr(inst, "_make_crawler", lambda: _FakeCrawler(results))
    return inst


ALL = [GOOD, LOOP, EMPTY, CERT, ESCAPES, PRIVATE, MALFORMED]


def test_crawl4ai_fetch_many_reports_each_url_it_gave_up_on(monkeypatch):
    results = _run(_provider(monkeypatch)._fetch_many_async(ALL))

    assert [r.url for r in results] == [GOOD]
    failures = {f["url"]: f["error"] for f in results.failures}
    assert set(failures) == set(ALL) - {GOOD}
    assert "ERR_TOO_MANY_REDIRECTS" in failures[LOOP]
    assert "anti-bot" in failures[EMPTY]
    assert "ERR_CERT_AUTHORITY_INVALID" in failures[CERT]
    assert "ended at refused URL" in failures[ESCAPES]
    assert "non-public address" in failures[PRIVATE]
    assert "unparseable" in failures[MALFORMED]


@pytest.fixture
def vault_dir(tmp_path: Path) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Lost URLs"])
    assert result.exit_code == 0
    root = tmp_path / "kb"
    os.chdir(root)
    return root


def test_fetch_batch_lists_every_url_crawl4ai_lost(vault_dir: Path, monkeypatch):
    inst = _provider(monkeypatch)
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: inst)

    # A malformed URL is refused before the provider: see test_fork_fetch_malformed_url.
    urls = [u for u in ALL if u != MALFORMED]
    result = runner.invoke(app, ["fetch-batch", *urls, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]

    assert [n["url"] for n in data["notes_created"]] == [GOOD]
    failed = {f["url"]: f for f in data["failed_urls"]}
    assert set(failed) == set(urls) - {GOOD}
    assert {f["phase"] for f in failed.values()} == {"batch"}
    assert data["total_fetched"] + data["skipped"] + len(data["failed_urls"]) == len(urls)


class _SilentlyDroppingProvider:
    """A fetch_many that returns a plain list and simply omits a URL."""

    name = "fake-drop"

    def fetch(self, url: str) -> WebResult:  # pragma: no cover - not used
        raise AssertionError("fetch_many should serve the whole batch")

    def fetch_many(self, urls):
        return [WebResult(url=u, title="Kept", content=TEXT) for u in urls if "lost" not in u]


def test_a_url_a_provider_drops_without_a_word_is_still_failed(vault_dir: Path, monkeypatch):
    monkeypatch.setattr(
        "hyperresearch.web.base.get_provider", lambda *a, **k: _SilentlyDroppingProvider()
    )
    kept, lost = "https://a.example.org/kept", "https://a.example.org/lost"

    result = runner.invoke(app, ["fetch-batch", kept, lost, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]

    assert [n["url"] for n in data["notes_created"]] == [kept]
    [failure] = data["failed_urls"]
    assert failure["url"] == lost
    assert failure["phase"] == "batch"


def test_batch_results_is_a_list_of_the_successes():
    batch = BatchResults([WebResult(url="https://a.example.org/", title="t", content="c")])
    batch.fail("https://b.example.org/", "boom")
    assert [r.url for r in batch] == ["https://a.example.org/"]
    assert batch.failures == [{"url": "https://b.example.org/", "error": "boom"}]
