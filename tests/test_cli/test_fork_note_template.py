"""`note new --template` writes the note through write_note, like the plain path.

The template path substituted the title and tags into the template's YAML as
text and wrote the result itself:
- a title with `"` or a tag like `#ai` made the YAML invalid, so the command
  crashed and left a file every later sync failed to read;
- the id was rendered before the collision loop, so a second note with the
  same title was written to foo-2.md with `id: foo` and never indexed, while
  the command reported id foo;
- --body/--body-file, --summary, --source, --status, --type, --tier and
  --content-type were ignored, and --tag too with the vault's default `note`
  template (`tags: []`).
The template's frontmatter is now parsed with the placeholders standing in,
used as defaults under the command-line options, and written by write_note.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.frontmatter import parse_frontmatter

runner = CliRunner()


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    result = runner.invoke(app, ["init", str(tmp_path / "v")])
    assert result.exit_code == 0, result.output
    monkeypatch.chdir(tmp_path / "v")
    return tmp_path / "v"


def _new(*args: str) -> dict:
    result = runner.invoke(app, ["note", "new", *args, "--json"])
    assert result.exit_code == 0, result.output
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is True
    return envelope["data"]


def _read(root: Path, rel: str):
    return parse_frontmatter((root / rel).read_text(encoding="utf-8"))


def _sync_errors() -> list:
    result = runner.invoke(app, ["sync", "--json"])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)["data"]["errors"]


def _indexed_ids() -> set[str]:
    from hyperresearch.core.vault import Vault

    return {r["id"] for r in Vault.discover().db.execute("SELECT id FROM notes")}


def test_title_with_quotes_and_hash_tag(root):
    quoted = _new('He said "hi"', "--template", "note")
    hashed = _new("Hash tag", "--template", "concept", "--tag", "#ai")
    meta, body = _read(root, quoted["path"])
    assert meta.title == 'He said "hi"'
    assert body.startswith('# He said "hi"\n')
    meta, body = _read(root, hashed["path"])
    assert meta.tags == ["#ai"]
    assert "## Definition" in body
    assert _sync_errors() == []
    assert {quoted["id"], hashed["id"]} <= _indexed_ids()


def test_existing_title_gets_a_free_id_that_is_in_the_file(root):
    first = _new("Foo", "--template", "concept")
    second = _new("Foo", "--template", "concept")
    assert first["id"] == "foo"
    assert second["id"] == "foo-2"
    assert second["path"] == "research/notes/foo-2.md"
    assert _read(root, second["path"])[0].id == "foo-2"
    assert _sync_errors() == []
    assert {"foo", "foo-2"} <= _indexed_ids()


def test_id_held_by_a_moved_note_is_not_reused(root):
    _new("Foo", "--template", "concept")
    assert runner.invoke(app, ["note", "mv", "foo", "foo-moved"]).exit_code == 0
    again = _new("Foo", "--template", "concept")
    assert again["id"] == "foo-2"
    assert _sync_errors() == []


def test_options_are_applied_over_the_template(root, tmp_path):
    body_file = tmp_path / "body.md"
    body_file.write_text("IMPORTANT FINDINGS\n", encoding="utf-8")
    data = _new(
        "Templated", "--template", "concept", "--body-file", str(body_file),
        "--summary", "my summary", "--source", "https://example.com",
        "--status", "review", "--type", "moc", "--tier", "institutional",
        "--content-type", "paper", "--parent", "ml",
    )
    meta, body = _read(root, data["path"])
    assert body == "IMPORTANT FINDINGS\n"
    assert meta.summary == "my summary"
    assert meta.source == "https://example.com"
    assert meta.status == "review"
    assert meta.type == "moc"
    assert meta.tier == "institutional"
    assert meta.content_type == "paper"
    assert meta.parent == "ml"
    # The layout is flat, as for every other note: parent is frontmatter.
    assert data["path"] == "research/notes/templated.md"


def test_tag_with_the_vault_default_note_template(root):
    data = _new("Tagged", "--template", "note", "--tag", "ml")
    assert _read(root, data["path"])[0].tags == ["ml"]


def test_tag_placeholder_and_option_give_each_tag_once(root):
    data = _new("Concept", "--template", "concept", "--tag", "ml", "--tag", "nlp")
    assert _read(root, data["path"])[0].tags == ["ml", "nlp"]


@pytest.mark.parametrize("flag", ["--body", "--body-stdin"])
def test_body_and_stdin_replace_the_template_body(root, flag):
    args = ["note", "new", "B", "--template", "guide", "--json"]
    if flag == "--body":
        result = runner.invoke(app, [*args, "--body", "given body"])
    else:
        result = runner.invoke(app, [*args, "--body-stdin"], input="given body")
    assert result.exit_code == 0, result.output
    path = json.loads(result.stdout)["data"]["path"]
    assert _read(root, path)[1] == "given body"


def test_template_defaults_are_kept_when_not_overridden(root):
    ref = _new("A Paper", "--template", "reference")
    moc = _new("Machine Learning", "--template", "moc")
    meta, body = _read(root, ref["path"])
    assert meta.type == "raw"
    assert meta.status == "draft"
    assert "## Citation" in body
    meta, _ = _read(root, moc["path"])
    assert meta.type == "moc"
    assert meta.summary == "Map of content for Machine Learning"


def test_custom_template_keeps_its_own_keys_and_tags(root):
    (root / ".hyperresearch" / "templates" / "paper.md").write_text(
        "---\n"
        'title: "{{ title }}"\n'
        "authors: []\n"
        "tags: [paper, {{ tags }}]\n"
        "venue: TBD\n"
        "---\n\n"
        "# {{ title }}\n\nCreated {{ created }}.\n",
        encoding="utf-8",
    )
    data = _new("Attention: \"all\" you need", "--template", "paper", "--tag", "ml")
    text = (root / data["path"]).read_text(encoding="utf-8")
    meta, body = parse_frontmatter(text)
    assert meta.title == 'Attention: "all" you need'
    assert meta.tags == ["paper", "ml"]
    assert meta.venue == "TBD"
    assert "authors: []" in text
    assert body.startswith('# Attention: "all" you need\n\nCreated 2')
    assert _sync_errors() == []


def test_invalid_template_is_a_json_error_and_writes_nothing(root):
    (root / ".hyperresearch" / "templates" / "broken.md").write_text(
        "---\ntitle: [unclosed\n---\n\nBody\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["note", "new", "X", "--template", "broken", "--json"])
    assert result.exit_code == 1
    envelope = json.loads(result.stdout)
    assert envelope["ok"] is False
    assert envelope["error_code"] == "INVALID_TEMPLATE"
    assert list((root / "research" / "notes").glob("*.md")) == []
