"""Numbers and dates in string fields, and a scalar `aliases:`, are read as the
user wrote them instead of keeping the note out of the index.

Hand-written YAML reads `title: 1984` and `summary: 42` as ints and
`aliases: foo` as a string. NoteMeta only coerced tags and id, so each of these
raised a ValidationError in parse_frontmatter and sync skipped the note on
every run. Booleans are still rejected (`title: yes`), as for tags: read as
'true' they would be written back over the user's value.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.frontmatter import parse_frontmatter, render_note

runner = CliRunner()


def _parse(fm: str):
    return parse_frontmatter(f"---\n{fm}\n---\n\nBody\n")[0]


def test_numeric_and_date_string_fields_are_read_as_strings():
    meta = _parse("title: 1984\nsummary: 42\nparent: 2024\nvenue: 3.5\nsource: 2024-01-02")
    assert meta.title == "1984"
    assert meta.summary == "42"
    assert meta.parent == "2024"
    assert meta.venue == "3.5"
    assert meta.source == str(date(2024, 1, 2))


@pytest.mark.parametrize("fm", ["title: yes", "title: T\nsummary: no", "title: T\naliases: [on]"])
def test_booleans_are_still_rejected(fm):
    with pytest.raises(ValidationError):
        _parse(fm)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("foo", ["foo"]),
        ("foo, Bar Baz", ["foo", "Bar Baz"]),
        ("[2024]", ["2024"]),
        ("[foo, 7]", ["foo", "7"]),
        ("2024-01-02", ["2024-01-02"]),
        ("", []),
        ("[]", []),
    ],
)
def test_aliases_scalar_comma_and_numbers(value, expected):
    assert _parse(f"title: T\naliases: {value}").aliases == expected


def test_aliases_keep_their_case():
    assert _parse("title: T\naliases: [GPT-4, Llama]").aliases == ["GPT-4", "Llama"]


def test_numeric_title_round_trips_as_a_string():
    meta = _parse("title: 1984")
    again, _ = parse_frontmatter(render_note(meta, "Body\n"))
    assert again.title == "1984"


def test_sync_indexes_numeric_titles_and_scalar_aliases(tmp_path: Path, monkeypatch):
    root = tmp_path / "v"
    assert runner.invoke(app, ["init", str(root)]).exit_code == 0
    monkeypatch.chdir(root)
    notes = root / "research" / "notes"
    (notes / "n1.md").write_text("---\ntitle: 1984\n---\nbody\n", encoding="utf-8")
    (notes / "n2.md").write_text("---\ntitle: S\nsummary: 42\n---\nbody\n", encoding="utf-8")
    (notes / "n3.md").write_text("---\ntitle: A\naliases: foo\n---\nbody\n", encoding="utf-8")
    (notes / "n4.md").write_text("---\ntitle: B\naliases: [2024]\n---\nbody\n", encoding="utf-8")
    result = runner.invoke(app, ["sync", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)["data"]
    assert data["errors"] == []
    assert data["added"] == 4

    from hyperresearch.core.vault import Vault

    db = Vault.discover().db
    titles = {r["id"]: r["title"] for r in db.execute("SELECT id, title FROM notes")}
    assert titles["n1"] == "1984"
    aliases = {(r["note_id"], r["alias"]) for r in db.execute("SELECT note_id, alias FROM aliases")}
    assert aliases == {("n3", "foo"), ("n4", "2024")}
