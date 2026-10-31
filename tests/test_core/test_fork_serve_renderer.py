"""The viewer's markdown renderer (serve/renderer.py)."""

from __future__ import annotations

import html
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


def test_fenced_code_is_escaped_exactly_once():
    out = render_markdown('```\nif a < b && c > d: print("x")\n```\n')

    assert '<pre><code class="language-">if a &lt; b &amp;&amp; c &gt; d: print(&quot;x&quot;)\n</code></pre>' in out


def test_fenced_code_keeps_its_language_and_stays_inert():
    out = render_markdown("```python\n<script>alert(1)</script>\n```\n")

    assert '<code class="language-python">&lt;script&gt;alert(1)&lt;/script&gt;\n</code>' in out
    assert "<script>" not in out


@pytest.mark.parametrize(
    "body",
    [
        "[a](http://x/![b](x onmouseover=alert))",
        "[a](http://x/[[t onmouseover=alert autofocus]])",
        "![a](http://x/[[t onerror=alert]])",
        "![a](http://x/[b](x onerror=alert))",
    ],
    ids=["image-in-link-url", "wiki-in-link-url", "wiki-in-image-url", "link-in-image-url"],
)
def test_text_inside_a_url_cannot_add_attributes(body):
    """A URL goes into an href or src attribute, and the image, link and
    wiki-link patterns still run over the text afterwards. Markup one of them
    renders inside the attribute ends it at its first quote, and the note text
    after that becomes attributes of its own, such as an event handler."""
    assert _event_handlers(render_markdown(body)) == []


def test_brackets_in_a_url_survive_as_character_references():
    """The browser decodes them, so the link still goes to the same place."""
    out = render_markdown("[local](http://[::1]:8080/x?a[]=1)")

    assert '<a href="http://&#91;::1&#93;:8080/x?a&#91;&#93;=1">local</a>' in out
    assert html.unescape("http://&#91;::1&#93;:8080/x?a&#91;&#93;=1") == "http://[::1]:8080/x?a[]=1"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("![diagram](https://example.com/d.png)", '<img src="https://example.com/d.png" alt="diagram">'),
        ("![](https://example.com/d.png)", '<img src="https://example.com/d.png" alt="">'),
        ('![a "b" & c](d.png)', '<img src="d.png" alt="a &quot;b&quot; &amp; c">'),
        (
            "[![badge](https://example.com/b.svg)](https://example.com)",
            '<a href="https://example.com"><img src="https://example.com/b.svg" alt="badge"></a>',
        ),
    ],
    ids=["image", "empty-alt", "alt-escaped", "linked-image"],
)
def test_images_render_as_img(body, expected):
    out = render_markdown(body)

    assert expected in out
    assert "!<a" not in out


def test_image_with_a_script_url_keeps_only_its_alt_text():
    out = render_markdown("![pic](javascript:alert(1))")

    assert "<img" not in out
    assert "javascript:" not in out
    assert "pic" in out


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("> quoted source line\n\nAfter.\n", "<blockquote>quoted source line</blockquote>"),
        (">no space\n", "<blockquote>no space</blockquote>"),
        ("> a & <b> [x](https://example.com)\n", '<blockquote>a &amp; &lt;b&gt; <a href="https://example.com">x</a></blockquote>'),
    ],
    ids=["quote", "no-space", "escaped-and-linked"],
)
def test_blockquotes_render(body, expected):
    """The body is escaped before the patterns run, so a quote line starts with
    '&gt;' by then; a pattern looking for '>' never matched."""
    assert expected in render_markdown(body)


def test_blockquote_marker_counts_only_at_line_start_and_stays_on_its_line():
    out = render_markdown("a > b\n>\nnext line\n")

    assert out.count("<blockquote>") == 1
    assert "a &gt; b" in out
    assert "next line</blockquote>" not in out


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("[[Tom & Jerry]]", '<a href="/note/tom-jerry" class="wiki-link">Tom &amp; Jerry</a>'),
        ("[[Tom & Jerry|cartoon]]", '<a href="/note/tom-jerry" class="wiki-link">cartoon</a>'),
        # sync strips a trailing backslash (shell escaping) from the ref it stores
        ("[[Tom & Jerry\\]]", '<a href="/note/tom-jerry" class="wiki-link">Tom &amp; Jerry\\</a>'),
        ("[[Elsewhere]]", '<a href="/note/Elsewhere" class="wiki-link">Elsewhere</a>'),
    ],
    ids=["resolved", "resolved-display", "trailing-backslash", "unresolved"],
)
def test_wiki_link_uses_the_resolved_note_id(body, expected):
    """Refs are looked up as sync stored them: unescaped text."""
    assert expected in render_markdown(body, {"Tom & Jerry": "tom-jerry"})
