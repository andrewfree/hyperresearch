"""Transient Windows replacement refusals must not lose completed writes."""

from pathlib import Path

import pytest


def test_windows_replace_retries_permission_errors(tmp_path, monkeypatch):
    from hyperresearch.core import files

    monkeypatch.setattr(files, "_WINDOWS", True)
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"new")
    target.write_bytes(b"old")
    replace = Path.replace
    attempts, sleeps = [], []

    def transient(self, destination):
        attempts.append(destination)
        if len(attempts) < 3:
            raise PermissionError("held by indexer")
        return replace(self, destination)

    monkeypatch.setattr(Path, "replace", transient)
    monkeypatch.setattr(files.time, "sleep", sleeps.append)
    files.replace_file(source, target)
    assert len(attempts) == 3
    assert len(sleeps) == 2
    assert all(0 < delay <= 0.2 for delay in sleeps)
    assert target.read_bytes() == b"new"
    assert not source.exists()


@pytest.mark.parametrize("windows,exception", [
    (False, PermissionError), (True, PermissionError), (True, FileNotFoundError),
])
def test_replace_retry_is_bounded_and_windows_permission_only(tmp_path, monkeypatch, windows, exception):
    from hyperresearch.core import files

    monkeypatch.setattr(files, "_WINDOWS", windows)
    attempts, sleeps = [], []
    error = exception("permanent refusal")

    def refuse(self, destination):
        attempts.append(destination)
        raise error

    monkeypatch.setattr(Path, "replace", refuse)
    monkeypatch.setattr(files.time, "sleep", sleeps.append)
    with pytest.raises(exception) as caught:
        files.replace_file(tmp_path / "source", tmp_path / "target")
    assert caught.value is error
    if windows and exception is PermissionError:
        assert 2 <= len(attempts) <= 10
        assert len(sleeps) == len(attempts) - 1
    else:
        assert len(attempts) == 1
        assert sleeps == []


@pytest.mark.parametrize("kind", ["manifest", "index"])
@pytest.mark.parametrize("permanent", [False, True])
def test_writers_retry_and_clean_up_temp_files(tmp_vault, monkeypatch, kind, permanent):
    from hyperresearch.core import files, runs
    from hyperresearch.indexgen.generator import IndexGenerator

    runs.init_run(tmp_vault, "dis-cccccc")
    monkeypatch.setattr(files, "_WINDOWS", True)
    monkeypatch.setattr(files.time, "sleep", lambda delay: None)
    replace = Path.replace
    attempts = []

    def transient(self, destination):
        attempts.append(destination)
        if permanent or len(attempts) == 1:
            raise PermissionError("held open")
        return replace(self, destination)

    monkeypatch.setattr(Path, "replace", transient)
    if kind == "manifest":
        directory = tmp_vault.run_dir("dis-cccccc")
        def write():
            runs._save(tmp_vault, "dis-cccccc", {"saved": True})
    else:
        generator = IndexGenerator(tmp_vault)
        directory = tmp_vault.index_dir
        def write():
            generator._replace_file("_index.md", "new page")
    if permanent:
        with pytest.raises(PermissionError):
            write()
    else:
        write()
        assert len(attempts) == 2
    assert list(directory.glob("*.tmp")) == []
