"""Case-insensitive link matching follows Unicode casefold rules."""

import pytest

from hyperresearch.core.note import write_note
from hyperresearch.models.note import slugify


@pytest.mark.parametrize("kind", ["id", "alias", "title"])
@pytest.mark.parametrize("target,ref", [("Ünïcode Target", "ÜNÏCODE TARGET"), ("Straße", "STRASSE")])
def test_unicode_links_resolve_when_target_arrives(tmp_vault, kind, target, ref):
    if kind == "id":
        target, ref = slugify(target), ref.replace(" ", "-")
    write_note(tmp_vault.notes_dir, "Source", body=f"See [[{ref}]].")
    tmp_vault.auto_sync()
    assert tmp_vault.db.execute("SELECT target_id FROM links").fetchone()[0] is None
    kwargs = {"note_id": target if kind == "id" else "target-note"}
    if kind == "alias":
        kwargs["extra_frontmatter"] = {"aliases": [target]}
    write_note(tmp_vault.notes_dir, target if kind == "title" else "Target", **kwargs)
    tmp_vault.auto_sync()
    assert tmp_vault.db.execute("SELECT target_id FROM links").fetchone()[0] == kwargs["note_id"]
