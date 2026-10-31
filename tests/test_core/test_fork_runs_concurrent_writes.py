"""Parallel writers to one run manifest must not lose each other's updates.

Every manifest change was load run.json, modify, save, with no lock, so two
`run step` or `run event` calls in flight together (a dissertation run keeps
several chapters in flight) both loaded the same manifest and the second save
dropped the first one's step or chapter while both exited 0. Every writer also
staged its save in the same run.json.tmp, so one writer's replace() could move
another's file away and crash it with FileNotFoundError.
"""

from __future__ import annotations

import json
import multiprocessing
import threading
from pathlib import Path

from hyperresearch.core import runs as runs_mod
from hyperresearch.core.levers import render_shims
from hyperresearch.core.runs import init_run, load_manifest, record_event, set_step

TAG = "dis-cccccc"


def _hold_first_load(monkeypatch, parties: int = 2, timeout: float = 3.0) -> None:
    """Make each thread's first manifest load wait until every thread has
    loaded: the interleaving that loses an update without a lock. A writer
    that is instead waiting on the run lock never arrives, so the barrier
    times out and the lock holder carries on alone."""
    real_load = runs_mod.load_manifest
    barrier = threading.Barrier(parties, timeout=timeout)
    state = threading.local()

    def load_in_lockstep(vault, vault_tag):
        manifest = real_load(vault, vault_tag)
        if not getattr(state, "waited", False):
            state.waited = True
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return manifest

    monkeypatch.setattr(runs_mod, "load_manifest", load_in_lockstep)


def _run_threads(*calls) -> list[BaseException]:
    """Run each zero-argument callable in its own thread; return what they raised."""
    errors: list[BaseException] = []

    def run(call):
        try:
            call()
        except BaseException as exc:  # surfaced by the caller; a thread swallows it otherwise
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(call,)) for call in calls]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return errors


def test_two_step_updates_that_load_together_both_land(tmp_vault, monkeypatch):
    init_run(tmp_vault, TAG, profile="dissertation")
    _hold_first_load(monkeypatch)
    errors = _run_threads(
        lambda: set_step(tmp_vault, TAG, "3", "running"),
        lambda: set_step(tmp_vault, TAG, "5", "running"),
    )
    assert errors == []
    assert set(load_manifest(tmp_vault, TAG)["steps"]) == {"3", "5"}


def test_two_chapter_plans_that_load_together_both_land(tmp_vault, monkeypatch):
    init_run(tmp_vault, TAG, profile="dissertation")
    _hold_first_load(monkeypatch)
    errors = _run_threads(
        lambda: record_event(tmp_vault, TAG, {"type": "chapter-plan", "chapter": "ch1"}),
        lambda: record_event(tmp_vault, TAG, {"type": "chapter-plan", "chapter": "ch2"}),
    )
    assert errors == []
    assert set(load_manifest(tmp_vault, TAG)["chapters"]) == {"ch1", "ch2"}


def test_levers_render_and_a_step_that_load_together_both_land(tmp_vault, monkeypatch):
    """`levers render` records the levers on the manifest the same way."""
    init_run(tmp_vault, TAG)
    (tmp_vault.run_dir(TAG) / "prompt-decomposition.json").write_text(
        json.dumps({"levers": {"register": "survey"}}), encoding="utf-8"
    )
    _hold_first_load(monkeypatch)
    errors = _run_threads(
        lambda: render_shims(tmp_vault, TAG),
        lambda: set_step(tmp_vault, TAG, "2", "running"),
    )
    assert errors == []
    manifest = load_manifest(tmp_vault, TAG)
    assert manifest["levers"]["register"] == "survey"
    assert set(manifest["steps"]) == {"2"}


def test_saves_in_flight_together_do_not_share_a_temp_file(tmp_vault, monkeypatch):
    """Both writers stage their file before either moves it into place."""
    init_run(tmp_vault, TAG)
    manifest = load_manifest(tmp_vault, TAG)
    real_replace = Path.replace
    barrier = threading.Barrier(2, timeout=10)
    state = threading.local()

    def replace_in_lockstep(self, target):
        if not getattr(state, "waited", False):
            state.waited = True
            barrier.wait()
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", replace_in_lockstep)
    errors = _run_threads(
        lambda: runs_mod._save(tmp_vault, TAG, dict(manifest)),
        lambda: runs_mod._save(tmp_vault, TAG, dict(manifest)),
    )
    assert errors == []
    assert load_manifest(tmp_vault, TAG)["vault_tag"] == TAG
    assert [p.name for p in tmp_vault.run_dir(TAG).glob("*.tmp")] == []


def _step_after_barrier(root: str, step: str, barrier, out) -> None:
    from hyperresearch.core.vault import Vault

    vault = Vault.discover(Path(root))
    barrier.wait()
    try:
        set_step(vault, TAG, step, "running")
        out.put((step, None))
    except BaseException as exc:
        out.put((step, repr(exc)))


def _chapter_after_barrier(root: str, chapter: str, barrier, out) -> None:
    from hyperresearch.core.vault import Vault

    vault = Vault.discover(Path(root))
    barrier.wait()
    try:
        record_event(vault, TAG, {"type": "chapter-plan", "chapter": chapter})
        out.put((chapter, None))
    except BaseException as exc:
        out.put((chapter, repr(exc)))


def _run_processes(target, root: Path, keys: list[str]) -> dict[str, str | None]:
    ctx = multiprocessing.get_context("spawn")
    barrier = ctx.Barrier(len(keys), timeout=60)
    out = ctx.Queue()
    procs = [ctx.Process(target=target, args=(str(root), k, barrier, out)) for k in keys]
    for p in procs:
        p.start()
    results = dict(out.get(timeout=120) for _ in keys)
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    return results


def test_parallel_run_step_processes_keep_every_step(tmp_vault):
    """Real processes released together, as `run step` calls from parallel
    chapter workers are."""
    init_run(tmp_vault, TAG, profile="dissertation")
    steps = [str(i) for i in range(1, 13)]
    results = _run_processes(_step_after_barrier, tmp_vault.root, steps)
    assert results == dict.fromkeys(steps)
    assert set(load_manifest(tmp_vault, TAG)["steps"]) == set(steps)


def test_parallel_chapter_plan_events_register_every_chapter(tmp_vault):
    init_run(tmp_vault, TAG, profile="dissertation")
    chapters = [f"ch{i}" for i in range(1, 7)]
    results = _run_processes(_chapter_after_barrier, tmp_vault.root, chapters)
    assert results == dict.fromkeys(chapters)
    assert set(load_manifest(tmp_vault, TAG)["chapters"]) == set(chapters)
    events = (tmp_vault.run_dir(TAG) / "events.jsonl").read_text(encoding="utf-8")
    assert events.count('"chapter-plan"') == 6
