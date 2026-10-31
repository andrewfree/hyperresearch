"""Markdown to HTML renderer with [[wiki-link]] resolution."""

from __future__ import annotations

import html
import re
import urllib.parse
from collections.abc import Mapping
from functools import partial


def path_href(prefix: str, segment: str) -> str:
    """``prefix`` plus ``segment`` percent-encoded as one path segment.

    The server unquotes the path, so this round-trips any id or tag. Without
    it a '#' or '?' in a tag cut the browser's request short and a literal
    '%20' was decoded to a space. quote() leaves nothing HTML-special, so the
    result is safe in an attribute as is.
    """
    return prefix + urllib.parse.quote(segment, safe="")


# Schemes a note body is allowed to link out to. Note bodies are fetched page
# content, so a URL in one is attacker-influenced: `javascript:` and `data:`
# both turn a rendered link into script execution in the viewer's origin.
# Relative and anchor targets carry no scheme and are always fine.
SAFE_URL_SCHEMES = frozenset({"http", "https", "mailto", "ftp"})

_SCHEME_RE = re.compile(r"^\s*([a-zA-Z][a-zA-Z0-9+.\-]*)\s*:")


def _is_safe_url(url: str) -> bool:
    """True unless `url` carries a scheme outside the allowlist.

    HTML entity decoding matters here: the URL has already been through
    `html.escape`, and a browser resolves `&#106;avascript:` back to
    `javascript:` when it parses the attribute.
    """
    probe = html.unescape(url).replace("\x00", "")
    # Browsers ignore control characters embedded in a scheme (`java\nscript:`).
    probe = "".join(c for c in probe if ord(c) > 0x20 or c == " ")
    m = _SCHEME_RE.match(probe)
    if m is None:
        return True  # relative path, anchor, or protocol-relative URL
    return m.group(1).lower() in SAFE_URL_SCHEMES


def _attr_url(url: str) -> str:
    """`url` for an href or src attribute, its brackets as character references.

    The image, link and wiki-link patterns run after this over the same text.
    Markup one of them rendered inside the attribute would end it at its first
    quote and turn the note text after it into attributes (an onerror=...).
    None of them can match without '['; the browser decodes the references.
    """
    return url.replace("[", "&#91;").replace("]", "&#93;")


def _link(url: str, text: str) -> str:
    if not _is_safe_url(url):
        return text  # keep the label, drop the link
    return f'<a href="{_attr_url(url)}">{text}</a>'


def _image(m: re.Match[str], *, allow_remote_images: bool = False) -> str:
    url, alt = m.group(2), m.group(1)
    # Match browser scheme handling and protocol-relative backslash URLs.
    probe = "".join(c for c in html.unescape(url) if ord(c) > 0x20).replace("\\", "/")
    scheme = _SCHEME_RE.match(probe)
    is_data_image = probe.lower().startswith("data:image/")
    if not is_data_image and not _is_safe_url(url):
        return alt
    remote = probe.startswith("//") or (scheme and scheme.group(1).lower() in {"http", "https"})
    if remote and not allow_remote_images:
        return _link(url, alt)
    return f'<img src="{_attr_url(url)}" alt="{alt}" referrerpolicy="no-referrer">'


# Bodies are fetched pages, and re.sub holds the GIL, so one quadratic scan
# stalls every viewer thread. No bracket pattern may rescan text that the
# next candidate scans again: link text stops at the next '[' and a URL at
# the next '(' or ')', so each byte is scanned a bounded number of times.
# A URL may still hold balanced (...) pairs, as Wikipedia URLs do. It never
# holds a raw '"': the body was escaped, so one is an image rendered just
# before ('[a](x![b](c))'), and its quotes would end the href.
_LINK_TEXT = r"[^\[\]\x00]"
_LINK_URL = r'((?:[^()"\x00]|\([^()"\x00]*\))+)'

_INLINE_PATTERNS = [
    # Bold/italic
    (re.compile(r"\*\*\*(.+?)\*\*\*"), r"<strong><em>\1</em></strong>"),
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"\*(.+?)\*"), r"<em>\1</em>"),
    # Code
    (re.compile(r"`([^`]+)`"), r"<code>\1</code>"),
]

# Simple markdown patterns
MD_PATTERNS = [
    # Headers
    (re.compile(r"^######\s+(.+)$", re.MULTILINE), r"<h6>\1</h6>"),
    (re.compile(r"^#####\s+(.+)$", re.MULTILINE), r"<h5>\1</h5>"),
    (re.compile(r"^####\s+(.+)$", re.MULTILINE), r"<h4>\1</h4>"),
    (re.compile(r"^###\s+(.+)$", re.MULTILINE), r"<h3>\1</h3>"),
    (re.compile(r"^##\s+(.+)$", re.MULTILINE), r"<h2>\1</h2>"),
    (re.compile(r"^#\s+(.+)$", re.MULTILINE), r"<h1>\1</h1>"),
    *_INLINE_PATTERNS,
    # Images, before links: the link pattern also matches the "[alt](url)"
    # inside "![alt](url)" and would leave "!<a ...>" behind.
    (re.compile(rf"!\[({_LINK_TEXT}*)\]\({_LINK_URL}\)"), _image),
    # Links
    (re.compile(rf"\[({_LINK_TEXT}+)\]\({_LINK_URL}\)"), lambda m: _link(m.group(2), m.group(1))),
    # Horizontal rule
    (re.compile(r"^---+$", re.MULTILINE), r"<hr>"),
    # Blockquotes. The body is escaped before these patterns run, so the
    # marker is '&gt;' by now; [ \t] rather than \s keeps a bare '>' line from
    # pulling the next line into its quote.
    (re.compile(r"^&gt;[ \t]*(.*)$", re.MULTILINE), r"<blockquote>\1</blockquote>"),
]


def render_markdown(
    body: str, resolved: Mapping[str, str] | None = None, *, allow_remote_images: bool = False,
) -> str:
    """Convert markdown body to HTML, resolving [[wiki-links]].

    ``resolved`` maps a link's ref, as sync stored it in the links table, to
    the note id sync resolved it to (by id, title, alias or case). A ref not
    in it links to its own text.
    """
    resolved = resolved or {}
    # Escape HTML first
    text = html.escape(body)

    # Handle code blocks (preserve them)
    code_blocks = []
    def save_code_block(m):
        code_blocks.append(m.group(0))
        return f"\x00CODE{len(code_blocks) - 1}\x00"

    text = re.sub(r"```(\w*)\n(.*?)```", save_code_block, text, flags=re.DOTALL)

    # Wiki links: [[target|display]] or [[target]]
    wiki_links = {}
    def replace_wiki_link(m):
        full = m.group(0)
        # Unescape the brackets that html.escape would have converted
        inner = full[2:-2]  # strip [[ and ]]
        if "|" in inner:
            target, display = inner.split("|", 1)
        else:
            target = display = inner
        target = target.strip()
        display = display.strip()
        # Look the ref up the way sync stored it: unescaped, trailing '\' dropped.
        ref = html.unescape(target).rstrip("\\")
        for pattern, replacement in _INLINE_PATTERNS:
            display = pattern.sub(replacement, display)
        placeholder = f"\x00WIKI{len(wiki_links)}\x00"
        wiki_links[placeholder] = (
            f'<a href="{path_href("/note/", resolved.get(ref, ref))}" class="wiki-link">{display}</a>'
        )
        return placeholder

    # Same bound as core.patterns.WIKI_LINK_RE: no '[' inside, one line only.
    text = re.sub(r'\[\[([^\[\]\n"]+)\]\]', replace_wiki_link, text)

    # Keep surrounding formatting out of refs. Link/image patterns exclude the
    # placeholder delimiter so restoration cannot put markup in an attribute.
    for pattern, replacement in MD_PATTERNS:
        if replacement is _image:
            replacement = partial(_image, allow_remote_images=allow_remote_images)
        text = pattern.sub(replacement, text)

    # Lists (simple)
    text = re.sub(r"^- (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
    text = re.sub(r"(<li>.*</li>\n?)+", lambda m: f"<ul>{m.group(0)}</ul>", text)

    # Tables
    lines = text.split("\n")
    in_table = False
    table_lines = []
    result_lines = []
    for line in lines:
        if "|" in line and line.strip().startswith("|"):
            if not in_table:
                in_table = True
                table_lines = []
            table_lines.append(line)
        else:
            if in_table:
                result_lines.append(_render_table(table_lines))
                in_table = False
                table_lines = []
            result_lines.append(line)
    if in_table:
        result_lines.append(_render_table(table_lines))
    text = "\n".join(result_lines)

    # One scan also keeps a page with many valid links linear in size.
    text = re.sub(r"\x00WIKI[0-9]+\x00", lambda m: wiki_links.get(m.group(0), m.group(0)), text)

    # Restore code blocks. They were saved from the already-escaped body, so
    # escaping them again showed '&lt;' and '&amp;' as literal text.
    for i, block in enumerate(code_blocks):
        lang_match = re.match(r"```(\w+)\n", block)
        lang = lang_match.group(1) if lang_match else ""
        code_content = re.sub(r"```\w*\n|```", "", block)
        code_html = f'<pre><code class="language-{lang}">{code_content}</code></pre>'
        text = text.replace(f"\x00CODE{i}\x00", code_html)

    # Paragraphs: wrap standalone lines
    text = re.sub(r"\n\n+", "\n</p>\n<p>\n", text)
    if not text.startswith("<"):
        text = "<p>\n" + text
    if not text.rstrip().endswith(">"):
        text = text + "\n</p>"

    return text


def _render_table(lines: list[str]) -> str:
    """Render a markdown table to HTML."""
    if len(lines) < 2:
        return "\n".join(lines)

    rows = []
    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip("|").split("|")]
        if i == 1 and all(re.match(r"^[-:]+$", c.strip()) for c in cells):
            continue  # Skip separator row
        tag = "th" if i == 0 else "td"
        row = "".join(f"<{tag}>{c}</{tag}>" for c in cells)
        rows.append(f"<tr>{row}</tr>")

    return f'<table class="md-table">{"".join(rows)}</table>'
