"""slugify keeps a combining mark only when it sits on a kept letter or digit.

Keeping every combining mark (for Indic vowel signs) also kept U+FE0F, the
variation selector that makes an emoji like '❤️' or '⚠️' render in colour.
It is a mark (Mn) but carries no meaning, so '❤️' and '⚠️' both became the
invisible id U+FE0F and collided, '⚠️ Known issues' got an id and filename
starting with an invisible character, and '1️⃣' kept its selector and keycap.
A mark left behind when the character under it was stripped also made a slug
that slugify changed again (NFC composed it with the letter before).

The strings are escaped: the selector is invisible in source.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.models.note import slugify

runner = CliRunner()

VS16 = "\ufe0f"
HEART = "❤" + VS16
WARNING = "⚠" + VS16
SUN = "☀" + VS16
KEYCAP_ONE = "1" + VS16 + "\u20e3"
KEYCAP_HASH = "#" + VS16 + "\u20e3"
ACUTE = "\u0301"
TILDE = "\u0303"


@pytest.mark.parametrize("title", [HEART, WARNING, SUN, KEYCAP_HASH])
def test_emoji_with_a_variation_selector_falls_back_to_the_hash(title):
    assert slugify(title).startswith("note-")


def test_distinct_emoji_with_a_variation_selector_get_distinct_ids():
    assert len({slugify(t) for t in (HEART, WARNING, SUN)}) == 3


def test_selectors_and_keycaps_stay_out_of_the_id():
    assert slugify(WARNING + " Known issues") == "known-issues"
    assert slugify(KEYCAP_ONE + " First step") == "1-first-step"


@pytest.mark.parametrize(
    ("title", "expected"),
    [("e!" + ACUTE, "e"), ("a " + ACUTE + "b", "a-b"), (ACUTE + "x", "x")],
)
def test_a_mark_whose_character_was_stripped_goes_too(title, expected):
    slug = slugify(title)
    assert slug == expected
    assert slugify(slug) == slug


def test_marks_on_letters_are_still_kept():
    hindi = "\u0939\u093f\u0928\u094d\u0926\u0940"  # हिन्दी
    assert slugify(hindi) == hindi
    assert slugify("q" + TILDE + " tilde") == "q" + TILDE + "-tilde"


def test_note_new_emoji_titles_get_visible_distinct_ids(tmp_path: Path, monkeypatch):
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    monkeypatch.chdir(root)

    def new(title: str) -> dict:
        result = runner.invoke(app, ["note", "new", title, "--json"])
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)["data"]

    first, second, third = new(HEART), new(WARNING), new(WARNING + " Known issues")
    assert first["id"] != second["id"]
    assert "warning" not in second
    assert third["id"] == "known-issues"
    assert not any(VS16 in d["path"] for d in (first, second, third))
