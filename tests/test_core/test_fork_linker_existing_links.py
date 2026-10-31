"""The auto-linker skips notes that already link a target, however the link
is written, and ignores mentions inside code.

existing_links held the raw `[[...]]` text and was compared to note ids, so a
note citing [[Attention Is All You Need]] by title (or by a case variant or
with a #fragment, which sync resolves) got a second, redundant link. Mentions
were checked against ``` fences only, so one inside inline code was linked.
"""

from __future__ import annotations

import pytest

from hyperresearch.core.linker import auto_link

TARGET = "attention-is-all-you-need"


@pytest.fixture
def link_vault(tmp_vault):
    from hyperresearch.core.note import write_note
    from hyperresearch.core.sync import compute_sync_plan, execute_sync

    notes = {
        "Attention Is All You Need": "The transformer paper.",
        "Title Citer": "Cites [[Attention Is All You Need]]. As Attention Is All You Need showed.",
        "Case Citer": "Cites [[ATTENTION-IS-ALL-YOU-NEED]]. As Attention Is All You Need showed.",
        "Fragment Citer": f"See [[{TARGET}#results]]. As Attention Is All You Need showed.",
        "Inline Code Only": "Mentioned only as `Attention Is All You Need` in code.",
        "Fenced Only": "Example:\n\n```\nAttention Is All You Need\n```\n",
        "Plain Mention": "The paper Attention Is All You Need introduced transformers.",
        "Code Then Prose": "First `Attention Is All You Need`, then Attention Is All You Need in prose.",
        "Fence Then Prose": "```\nAttention Is All You Need\n```\n\nThen Attention Is All You Need in prose.",
    }
    for title, body in notes.items():
        write_note(tmp_vault.notes_dir, title, body=body)
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    return tmp_vault


def test_only_unlinked_prose_mentions_get_a_link(link_vault):
    report = auto_link(link_vault, dry_run=True)
    assert report == {
        "plain-mention": [TARGET],
        "code-then-prose": [TARGET],
        "fence-then-prose": [TARGET],
    }


def test_title_citer_file_is_left_alone(link_vault):
    path = link_vault.notes_dir / "title-citer.md"
    before = path.read_bytes()
    report = auto_link(link_vault)
    assert "title-citer" not in report
    assert path.read_bytes() == before
    assert "## Related" in (link_vault.notes_dir / "plain-mention.md").read_text(encoding="utf-8")
