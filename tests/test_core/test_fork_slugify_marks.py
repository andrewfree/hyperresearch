"""slugify keeps combining marks, so Indic and other abugida titles keep their
vowel signs.

`[^\\w\\s-]` strips every character that is not a letter, digit, underscore,
space or hyphen. Devanagari and Tamil vowel signs and viramas are combining
marks (Unicode categories Mn and Mc), not letters, so they were stripped:
'काम' (work) became 'कम' (less) and collided with the note titled 'कम', and
'हिन्दी' became 'हनद'.
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.models.note import slugify

runner = CliRunner()


@pytest.mark.parametrize("title", ["काम", "हिन्दी", "தமிழ்", "ಕನ್ನಡ", "สวัสดี"])
def test_abugida_titles_keep_their_vowel_signs(title):
    assert slugify(title) == unicodedata.normalize("NFC", title)


def test_titles_differing_only_in_a_vowel_sign_get_distinct_slugs():
    assert slugify("काम") != slugify("कम")


def test_slug_with_marks_is_a_fixed_point():
    for title in ("हिन्दी भाषा", "தமிழ் மொழி", "q̃ tilde"):
        slug = slugify(title)
        assert slugify(slug) == slug


def test_marks_on_latin_text_after_nfc_are_unchanged():
    # NFC composes é, so nothing about accented Latin slugs moves.
    assert slugify("Évolution des systèmes") == "évolution-des-systèmes"
    assert slugify("Python 3.12 Features!") == "python-312-features"


def test_note_new_gives_distinct_ids_and_no_false_duplicate_warning(tmp_path: Path, monkeypatch):
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    monkeypatch.chdir(root)
    first = json.loads(runner.invoke(app, ["note", "new", "काम", "--json"]).stdout)
    second = json.loads(runner.invoke(app, ["note", "new", "कम", "--json"]).stdout)
    assert first["data"]["id"] == "काम"
    assert second["data"]["id"] == "कम"
    assert "warning" not in second["data"]
