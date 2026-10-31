"""The viewer's markdown renderer (serve/renderer.py)."""

from __future__ import annotations

import time
from html.parser import HTMLParser

import pytest

from hyperresearch.serve.renderer import render_markdown


@pytest.mark.parametrize(
    "flood",
    ["[[a" * 20_000, "[a" * 30_000, "[" * 60_000, "[a](x" * 12_000, "![a](x" * 10_000, "[a](x(y)" * 7_500],
    ids=["[[a", "[a", "[", "[a](x", "![a](x", "[a](x(y)"],
)
def test_bracket_floods_render_in_linear_time(flood):
    """Note bodies are fetched pages, so hostile. The bracket patterns used to
    rescan to the next ']' or ')' from every '[': a 72 KB body took about 12 s,
    and re.sub holds the GIL, so every other page waited too."""
    started = time.perf_counter()
    render_markdown(flood)
    elapsed = time.perf_counter() - started

    assert elapsed < 1.0, f"{len(flood)} byte flood took {elapsed:.2f}s"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("[label](https://example.com/a)", '<a href="https://example.com/a">label</a>'),
        ("see [two\nlines](https://example.com)", '<a href="https://example.com">two\nlines</a>'),
        ("[my file](notes/my file.md)", '<a href="notes/my file.md">my file</a>'),
        (
            "[Foo](https://en.wikipedia.org/wiki/Foo_(bar))",
            '<a href="https://en.wikipedia.org/wiki/Foo_(bar)">Foo</a>',
        ),
        ("[a](https://x.example) and (aside)", '<a href="https://x.example">a</a> and (aside)'),
        ("[[target-note]]", '<a href="/note/target-note" class="wiki-link">target-note</a>'),
        ("[[target-note|the target]]", '<a href="/note/target-note" class="wiki-link">the target</a>'),
    ],
    ids=["link", "multiline-text", "space-in-url", "parens-in-url", "paren-after", "wiki", "wiki-display"],
)
def test_links_still_render_after_the_scan_bound(body, expected):
    assert expected in render_markdown(body)


class _HandlerFinder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.found: list[tuple[str, str]] = []

    def handle_starttag(self, tag, attrs):
        self.found += [(tag, name) for name, _ in attrs if name.startswith("on")]


def _event_handlers(markup: str) -> list[tuple[str, str]]:
    """Event-handler attributes in ``markup``, parsed the way a browser would."""
    finder = _HandlerFinder()
    finder.feed(markup)
    finder.close()
    return finder.found


@pytest.mark.parametrize(
    "body",
    ["[[t [a](x onmouseover=alert) u]]", "[[t ![b](x onmouseover=alert) u]]"],
    ids=["link-in-wiki", "image-in-wiki"],
)
def test_a_wiki_link_cannot_wrap_a_rendered_link(body):
    """With '[' kept out of link text, the inner link renders first and leaves
    '[[...]]' around it. Its quotes must not become part of a wiki href, where
    they would end the attribute and let note text add an event handler."""
    assert _event_handlers(render_markdown(body)) == []
