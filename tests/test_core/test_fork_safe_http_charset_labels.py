"""A <meta charset> label that cannot be the page's encoding is ignored.

The meta sniffer handed any name Python's codec registry knows to
bytes.decode. Python knows far more than the labels browsers accept, so a
page declaring utf-32, utf-7, an EBCDIC code page or punycode was decoded
into garbage and rejected as binary junk, and one declaring idna or
undefined raised UnicodeError, failing the fetch. Each page was saved
intact before meta sniffing existed. The declaration itself was read as
ASCII bytes, so a codec that does not decode ASCII as ASCII cannot be the
page's encoding; browsers ignore such labels and so does this.
"""

from __future__ import annotations

import pytest

from hyperresearch.web.safe_http import SafeResponse


def _page(label: str) -> str:
    return (
        f"<html><head><meta charset='{label}'><title>Grüße aus C++</title></head>"
        "<body><p>River sediments settle in estuaries, 50% of them by C++ models.</p></body></html>"
    )


@pytest.mark.parametrize(
    "label", ["utf-32", "utf-32le", "utf-7", "cp037", "ibm500", "punycode", "idna", "undefined", "hz"]
)
def test_a_label_that_does_not_read_ascii_as_ascii_falls_back_to_utf8(label: str):
    html = _page(label)
    resp = SafeResponse(
        url="https://site.example.org/p", status_code=200,
        headers={"content-type": "text/html"}, content=html.encode("utf-8"),
    )
    assert resp.text == html


@pytest.mark.parametrize("label", ["koi8-r", "gb18030", "big5", "euc-kr", "iso-2022-jp", "cp1251"])
def test_ascii_compatible_legacy_labels_still_decide(label: str):
    html = _page(label).replace("Grüße", "Тест" if label in ("koi8-r", "cp1251") else "測試")
    if label == "euc-kr":
        html = html.replace("測試", "시험")
    resp = SafeResponse(
        url="https://site.example.org/p", status_code=200,
        headers={"content-type": "text/html"}, content=html.encode(label),
    )
    assert resp.text == html
