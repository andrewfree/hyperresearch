"""Blocking an image preserves the destination of its surrounding link."""

from html.parser import HTMLParser

import pytest

from hyperresearch.serve.renderer import render_markdown


class Links(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.links = []
        self.images = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append(dict(attrs))
        elif tag == "img":
            self.images.append(dict(attrs))


@pytest.mark.parametrize("alt", ["badge", "**状态** & `status`", 'a "quoted" badge'])
def test_linked_remote_image_keeps_outer_destination(alt):
    rendered = render_markdown(f"[![{alt}](https://images.example/b.svg)](https://docs.example)")
    parsed = Links(rendered)

    assert parsed.images == []
    assert parsed.links == [{"href": "https://docs.example"}]
    assert rendered.count("</a>") == 1


def test_linked_remote_image_opt_in_still_renders_image():
    rendered = render_markdown(
        "[![badge](https://images.example/b.svg)](https://docs.example)",
        allow_remote_images=True,
    )
    parsed = Links(rendered)
    assert parsed.links == [{"href": "https://docs.example"}]
    assert parsed.images == [{
        "src": "https://images.example/b.svg", "alt": "badge", "referrerpolicy": "no-referrer",
    }]
