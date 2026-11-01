"""Formatting characters in wiki references must not change their targets."""

import time
from html.parser import HTMLParser

import pytest

from hyperresearch.serve.renderer import render_markdown


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


@pytest.mark.parametrize(("ref", "display"), [
    ("A* search", "A* search"),
    ("A **bold** title", "A <strong>bold</strong> title"),
    ("A `code` title", "A <code>code</code> title"),
])
@pytest.mark.parametrize("prefix", ["", "* ", "- "])
def test_wiki_refs_are_resolved_before_formatting(ref, display, prefix):
    rendered = render_markdown(f"{prefix}[[{ref}]]", {ref: "target-note"})
    links = [attrs for tag, attrs in Tags(rendered).tags if tag == "a"]

    assert links == [{"href": "/note/target-note", "class": "wiki-link"}]
    assert f">{display}</a>" in rendered


def test_wiki_display_and_target_stay_escaped():
    rendered = render_markdown(
        '[[A `code` & "title"|<img onerror=alert> & display]]',
        {'A `code` & "title"': "safe-target"},
    )
    assert '<a href="/note/safe-target" class="wiki-link">' in rendered
    assert "&lt;img onerror=alert&gt; &amp; display</a>" in rendered
    assert all(tag == "a" or tag == "p" for tag, _ in Tags(rendered).tags)


@pytest.mark.parametrize("body", [
    "[link](https://example.com/[[target onmouseover=alert]])",
    "![alt](local/[[target onerror=alert]])",
    "![[[target|label onerror=alert]]](local.png)",
])
def test_protected_wiki_spans_cannot_create_attributes(body):
    rendered = render_markdown(body)
    for _, attrs in Tags(rendered).tags:
        assert not any(name.startswith("on") for name in attrs)


def test_wiki_in_fenced_code_stays_literal():
    rendered = render_markdown("```\n[[A `code` title]]\n```", {"A `code` title": "target-note"})
    assert "<a " not in rendered
    assert "[[A `code` title]]" in rendered


def test_many_wiki_links_restore_in_linear_time():
    body = "[[target-note]] " * 20_000
    started = time.perf_counter()

    rendered = render_markdown(body)

    assert time.perf_counter() - started < 1.0
    assert rendered.count('class="wiki-link"') == 20_000


def test_wiki_display_keeps_existing_inline_formatting():
    rendered = render_markdown("[[target-note|**bold** and *italic* and `code`]]")

    assert '<a href="/note/target-note" class="wiki-link">' in rendered
    assert "<strong>bold</strong> and <em>italic</em> and <code>code</code></a>" in rendered
