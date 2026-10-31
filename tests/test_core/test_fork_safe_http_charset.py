"""SafeResponse.text honors the document's own charset declaration.

With no charset in the Content-Type header, the body was decoded as UTF-8
with errors=replace, whatever the page declared. A windows-1252 page was
saved with U+FFFD in place of every accented letter and smart quote, and a
Shift_JIS page was rejected by the junk gate as binary content, while the
same bytes worked when the header named the charset. Browsers (and the
crawl4ai lane) use the BOM and <meta charset> / http-equiv in that case.
"""

from __future__ import annotations

import pytest

from hyperresearch.web.builtin import BuiltinProvider
from hyperresearch.web.safe_http import SafeResponse

CP1252_TITLE = "Café crème — “quoted”"
JAPANESE = "日本語のテキストです。河川の堆積物について説明します。"


def _page(head: str, title: str, body: str) -> str:
    return f"<html><head>{head}<title>{title}</title></head><body><p>{body}</p></body></html>"


def _resp(body: bytes, content_type: str = "text/html") -> SafeResponse:
    headers = {"content-type": content_type} if content_type else {}
    return SafeResponse(url="https://site.example.org/p", status_code=200, headers=headers, content=body)


@pytest.mark.parametrize(
    "head",
    [
        "<meta charset='windows-1252'>",
        '<meta charset="windows-1252" />',
        '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=windows-1252">',
    ],
)
def test_meta_charset_decides_when_the_header_names_none(head: str):
    html = _page(head, CP1252_TITLE, "Naïve résumé")
    assert _resp(html.encode("cp1252")).text == html


def test_http_equiv_shift_jis_page_decodes():
    head = "<meta http-equiv='Content-Type' content='text/html; charset=Shift_JIS'>"
    html = _page(head, "河川の堆積物", JAPANESE)
    assert _resp(html.encode("shift_jis")).text == html


def test_an_iso_8859_1_label_decodes_as_windows_1252_like_browsers():
    """Smart quotes are 0x93/0x94 in such pages; latin-1 makes them C1 controls."""
    html = _page("<meta charset='iso-8859-1'>", CP1252_TITLE, "x")
    assert _resp(html.encode("cp1252")).text == html


def test_a_bom_wins_over_the_meta_declaration():
    html = _page("<meta charset='windows-1252'>", "BOM page", "Grüße")
    assert _resp(b"\xef\xbb\xbf" + html.encode("utf-8")).text == html
    assert _resp(html.encode("utf-16")).text == html


def test_the_header_charset_still_wins():
    html = _page("<meta charset='windows-1252'>", "河川", JAPANESE)
    assert _resp(html.encode("shift_jis"), "text/html; charset=Shift_JIS").text == html


def test_utf8_stays_the_default_and_unknown_labels_fall_back_to_it():
    html = _page("", "Grüße", "plain")
    assert _resp(html.encode("utf-8")).text == html
    odd = _page("<meta charset='no-such-codec'>", "Grüße", "plain")
    assert _resp(odd.encode("utf-8")).text == odd


def test_a_non_html_body_is_not_sniffed():
    body = '{"snippet": "<meta charset=\'windows-1252\'>", "name": "Grüße"}'
    assert _resp(body.encode("utf-8"), "application/json").text == body


def test_builtin_provider_saves_legacy_encoded_pages_intact(monkeypatch):
    pages = {
        "https://site.example.org/cp1252": _page(
            "<meta charset='windows-1252'>", CP1252_TITLE, "Naïve résumé. " * 40
        ).encode("cp1252"),
        "https://site.example.org/sjis": _page(
            "<meta http-equiv='Content-Type' content='text/html; charset=Shift_JIS'>",
            "河川の堆積物",
            JAPANESE * 20,
        ).encode("shift_jis"),
    }

    def fake_safe_get(url, **kwargs):
        return SafeResponse(url=url, status_code=200, headers={"content-type": "text/html"}, content=pages[url])

    monkeypatch.setattr("hyperresearch.web.safe_http.safe_get", fake_safe_get)
    prov = BuiltinProvider()

    latin = prov.fetch("https://site.example.org/cp1252")
    assert latin.title == CP1252_TITLE
    assert "Naïve résumé" in latin.content
    assert latin.looks_like_junk() is None

    japanese = prov.fetch("https://site.example.org/sjis")
    assert japanese.title == "河川の堆積物"
    assert japanese.looks_like_junk() is None
