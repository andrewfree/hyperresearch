"""Pages the viewer serves, requested over HTTP from a server running in-process."""

from __future__ import annotations

import html
import re
import urllib.parse
from http.client import HTTPConnection
from threading import Thread

import pytest

from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.serve.server import HyperresearchHandler, HyperresearchServer


@pytest.fixture
def viewer(tmp_vault, monkeypatch):
    monkeypatch.setattr(HyperresearchHandler, "vault", tmp_vault)
    with HyperresearchServer(("127.0.0.1", 0), HyperresearchHandler) as server:
        serving = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        serving.start()
        try:
            yield server.server_address
        finally:
            server.shutdown()
            serving.join(5)


def _sync(vault) -> None:
    execute_sync(vault, compute_sync_plan(vault, force=True))


def _get(address, path: str) -> tuple[int, str]:
    client = HTTPConnection(*address, timeout=5)
    try:
        client.request("GET", path)
        response = client.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        client.close()


def _main(page: str) -> str:
    return page.split("<main>", 1)[1].split("</main>", 1)[0]


def test_backlinks_list_each_linking_note_once(tmp_vault, viewer):
    """The links table holds one row per distinct ref per line; the panel shows
    only titles, so repeating a source once per row added nothing."""
    write_note(tmp_vault.notes_dir, "Target Note", body="target body")
    write_note(
        tmp_vault.notes_dir,
        "Linker",
        body="A [[target-note]] B [[Target Note]] C [[TARGET-NOTE]]\n\nAgain [[target-note]].\n",
    )
    write_note(tmp_vault.notes_dir, "Other", body="See [[target-note]].\n")
    _sync(tmp_vault)

    status, page = _get(viewer, "/note/target-note")

    assert status == 200
    backlinks = page.split('<div class="backlinks">', 1)[1].split("</div>", 1)[0]
    assert backlinks.count("<li>") == 2
    assert backlinks.count(">Linker</a>") == 1
    assert backlinks.count(">Other</a>") == 1


@pytest.mark.parametrize(
    "body",
    ["Hello world.\n", "## Section\n\nText.\n", "```\n# a comment, not a heading\n```\n", "#hashtag first\n"],
    ids=["plain", "h2-first", "code-first", "hashtag-first"],
)
def test_note_without_a_title_heading_shows_its_title(tmp_vault, viewer, body):
    """`note new --body`, `--body-file` and MCP create_note store the body as
    given, so most notes have no '# Title' line of their own."""
    write_note(tmp_vault.notes_dir, "Plain Note", body=body)
    _sync(tmp_vault)

    status, page = _get(viewer, "/note/plain-note")

    assert status == 200
    assert _main(page).count("<h1>Plain Note</h1>") == 1


def test_note_with_its_own_heading_gets_no_second_title(tmp_vault, viewer):
    write_note(tmp_vault.notes_dir, "Headed", body="\n# Headed Differently\n\nText.\n")
    _sync(tmp_vault)

    status, page = _get(viewer, "/note/headed")

    assert status == 200
    main = _main(page)
    assert main.count("<h1>") == 1
    assert "<h1>Headed Differently</h1>" in main


def test_shown_title_is_escaped(tmp_vault, viewer):
    write_note(tmp_vault.notes_dir, "Fish & <Chips>", note_id="fish", body="Text.\n")
    _sync(tmp_vault)

    status, page = _get(viewer, "/note/fish")

    assert status == 200
    assert "<h1>Fish &amp; &lt;Chips&gt;</h1>" in _main(page)


def _browser_request_target(href_attr: str) -> str:
    """What a browser requests for an href: the fragment is dropped, '?' starts
    the query, and only spaces and non-ASCII get percent-encoded."""
    parts = urllib.parse.urlsplit(html.unescape(href_attr))
    target = urllib.parse.quote(parts.path, safe="/%")
    return f"{target}?{parts.query}" if parts.query else target


@pytest.mark.parametrize("tag", ["c#", "what?", "a%20b", "a/b", "x y", "naïve"])
@pytest.mark.parametrize("linking_page", ["/note/tagged", "/tags"])
def test_tag_link_opens_that_tags_page(tmp_vault, viewer, tag, linking_page):
    write_note(tmp_vault.notes_dir, "Tagged", body="x", tags=[tag])
    _sync(tmp_vault)

    _, page = _get(viewer, linking_page)
    hrefs = re.findall(r'href="(/tag/[^"]*)"', page)
    assert len(hrefs) == 1
    status, tag_page = _get(viewer, _browser_request_target(hrefs[0]))

    assert status == 200
    assert f"<h1>Tag: {html.escape(tag)}</h1>" in tag_page
    assert "<p>1 notes</p>" in tag_page


def test_note_links_still_open_their_notes(tmp_vault, viewer):
    write_note(tmp_vault.notes_dir, "Café Notes", body="accented id\n")
    write_note(tmp_vault.notes_dir, "Plain", body="See [[café-notes]].\n")
    _sync(tmp_vault)

    _, index = _get(viewer, "/")
    hrefs = re.findall(r'href="(/note/[^"]*)"', _main(index))
    assert len(hrefs) == 2
    for href in hrefs:
        status, page = _get(viewer, _browser_request_target(href))
        assert status == 200
        assert re.search(r"<title>(Café Notes|Plain) \|", page)
