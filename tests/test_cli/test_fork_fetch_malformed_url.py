"""A URL urlparse cannot parse is an input error, not a crash.

urlparse raises ValueError for an unbalanced IPv6 bracket ("http://[::1",
"https://example.com]/x"). fetch-batch passed such a URL to extract_doi in
its blocked-URL loop, outside any handler, so one bad input aborted the whole
batch with a traceback and the good URLs were never written. `fetch` crashed
the same way in is_pdf_url and again in its rescue handler. Offline: a fake
provider serves the good URLs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.scholar import extract_doi
from hyperresearch.web.base import WebResult
from hyperresearch.web.pdf import is_pdf_url

runner = CliRunner()

GOOD = "https://site.example.org/article"
UNBALANCED = ["http://[::1", "https://example.com]/x"]
TEXT = "River sediments settle in estuaries over long periods of time. " * 20


class _StrictProvider:
    """Raises on a URL it cannot parse, as the builtin provider does."""

    name = "fake-strict"

    def __init__(self):
        self.calls: list[str] = []

    def fetch(self, url: str) -> WebResult:
        self.calls.append(url)
        if is_pdf_url(url):  # pragma: no cover - not a PDF URL
            raise AssertionError
        from urllib.parse import urlparse

        urlparse(url)
        return WebResult(url=url, title="River Sediments", content=TEXT)


@pytest.fixture
def prov(tmp_path: Path, monkeypatch) -> _StrictProvider:
    result = runner.invoke(app, ["init", str(tmp_path / "kb"), "--name", "Malformed"])
    assert result.exit_code == 0
    os.chdir(tmp_path / "kb")
    provider = _StrictProvider()
    monkeypatch.setattr("hyperresearch.web.base.get_provider", lambda *a, **k: provider)
    return provider


def test_fetch_batch_fails_the_bad_url_and_keeps_the_good_one(prov: _StrictProvider):
    result = runner.invoke(app, ["fetch-batch", GOOD, *UNBALANCED, "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]

    assert [n["url"] for n in data["notes_created"]] == [GOOD]
    failed = {f["url"]: f for f in data["failed_urls"]}
    assert set(failed) == set(UNBALANCED)
    assert {f["phase"] for f in failed.values()} == {"input"}
    assert all("Invalid IPv6 URL" in f["error"] for f in failed.values())
    assert prov.calls == [GOOD]


def test_fetch_batch_with_only_bad_urls_still_reports_them(prov: _StrictProvider):
    result = runner.invoke(app, ["fetch-batch", UNBALANCED[0], "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["notes_created"] == []
    assert [f["url"] for f in data["failed_urls"]] == [UNBALANCED[0]]


@pytest.mark.parametrize("url", UNBALANCED)
def test_fetch_answers_a_bad_url_with_an_error_envelope(prov: _StrictProvider, url: str):
    result = runner.invoke(app, ["fetch", url, "--json"])
    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "INVALID_URL"
    assert "Invalid IPv6 URL" in envelope["error"]
    assert prov.calls == []


def test_fetch_human_mode_prints_an_error_not_a_traceback(prov: _StrictProvider):
    result = runner.invoke(app, ["fetch", UNBALANCED[0]])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert "Invalid URL" in result.output


def test_extract_doi_and_is_pdf_url_do_not_raise_on_a_bad_url():
    assert is_pdf_url("http://[::1/paper.pdf") is False
    assert extract_doi("http://[::1", None, "see doi:10.1234/abc.5678 here") == "10.1234/abc.5678"
    assert extract_doi("https://example.com]/x") is None
