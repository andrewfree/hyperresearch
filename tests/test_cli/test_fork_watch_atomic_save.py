"""`watch` syncs a note saved by writing a temp file and renaming it.

Many editors and tools save atomically: they write `note.md.tmp` (or a
similar name) and rename it over `note.md`. The only event for the note is
the move, whose source is the temp name and whose destination is the note.
The handler looked at the source path alone, so the note stayed unindexed
until an unrelated `.md` write fired an event.

The observer is replaced by one that delivers a given event, and the clock by
one the watch loop's sleeps advance, so the test needs no real file events.
"""

from __future__ import annotations

import pytest

watchdog_events = pytest.importorskip("watchdog.events")


class _Clock:
    """Stands in for the `time` module in cli/watch.py: every sleep moves the
    clock on, and the loop stops after a few seconds of fake time."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps = 0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.now += seconds
        if self.sleeps > 20:
            raise KeyboardInterrupt


def _watch_with_events(monkeypatch, vault, make_events):
    """Run `watch` in `vault` with an observer that delivers `make_events()`
    once it starts; return the ids indexed when the loop stops."""
    import watchdog.observers

    import hyperresearch.cli.watch as watch_mod

    class _Observer:
        def schedule(self, handler, path, recursive=False):
            self.handler = handler

        def start(self):
            for event in make_events():
                self.handler.dispatch(event)

        def stop(self):
            pass

        def join(self):
            pass

    monkeypatch.setattr(watchdog.observers, "Observer", _Observer)
    monkeypatch.setattr(watch_mod, "time", _Clock())
    monkeypatch.chdir(vault.root)
    watch_mod.watch(rebuild_index=False, run_lint=False)
    return sorted(r["id"] for r in vault.db.execute("SELECT id FROM notes"))


def test_watch_syncs_a_note_renamed_into_place_from_a_temp_file(tmp_vault, monkeypatch):
    note = tmp_vault.notes_dir / "atomic.md"
    tmp = tmp_vault.notes_dir / "atomic.md.tmp"

    def atomic_save():
        tmp.write_text("---\ntitle: Atomic\n---\n\nbody\n", encoding="utf-8")
        tmp.rename(note)
        return [
            watchdog_events.FileCreatedEvent(str(tmp)),
            watchdog_events.FileModifiedEvent(str(tmp)),
            watchdog_events.FileMovedEvent(str(tmp), str(note)),
        ]

    assert _watch_with_events(monkeypatch, tmp_vault, atomic_save) == ["atomic"]


def test_watch_still_ignores_events_for_files_that_are_not_notes(tmp_vault, monkeypatch):
    """A temp file that is written and renamed to another non-note name is
    no reason to sync: a note written behind the watcher's back stays
    unindexed, as before."""
    (tmp_vault.notes_dir / "unseen.md").write_text("---\ntitle: Unseen\n---\n\nx\n", encoding="utf-8")
    scratch = tmp_vault.notes_dir / "data.json.tmp"

    def other_save():
        return [
            watchdog_events.FileCreatedEvent(str(scratch)),
            watchdog_events.FileMovedEvent(str(scratch), str(tmp_vault.notes_dir / "data.json")),
        ]

    assert _watch_with_events(monkeypatch, tmp_vault, other_save) == []
