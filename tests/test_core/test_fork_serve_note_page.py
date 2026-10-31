"""Pages the viewer serves, requested over HTTP from a server running in-process."""

from __future__ import annotations

from http.client import HTTPConnection
from threading import Thread

import pytest

from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.serve.server import HyperresearchHandler, HyperresearchServer


@pytest.fixture
def viewer(tmp_vault, monkeypatch):
    monkeypatch.setattr(HyperresearchHandler, "vault", tmp_vault)
    with HyperresearchServer(("127.0.0.1", 0), HyperresearchHandler) as server:
        serving = Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05})
        serving.start()
        try:
            yield server.server_address
        finally:
            server.shutdown()
            serving.join(5)


def _sync(vault) -> None:
    execute_sync(vault, compute_sync_plan(vault, force=True))


def _get(address, path: str) -> tuple[int, str]:
    client = HTTPConnection(*address, timeout=5)
    try:
        client.request("GET", path)
        response = client.getresponse()
        return response.status, response.read().decode("utf-8")
    finally:
        client.close()


def _main(page: str) -> str:
    return page.split("<main>", 1)[1].split("</main>", 1)[0]


def test_backlinks_list_each_linking_note_once(tmp_vault, viewer):
    """The links table holds one row per distinct ref per line; the panel shows
    only titles, so repeating a source once per row added nothing."""
    write_note(tmp_vault.notes_dir, "Target Note", body="target body")
    write_note(
        tmp_vault.notes_dir,
        "Linker",
        body="A [[target-note]] B [[Target Note]] C [[TARGET-NOTE]]\n\nAgain [[target-note]].\n",
    )
    write_note(tmp_vault.notes_dir, "Other", body="See [[target-note]].\n")
    _sync(tmp_vault)

    status, page = _get(viewer, "/note/target-note")

    assert status == 200
    backlinks = page.split('<div class="backlinks">', 1)[1].split("</div>", 1)[0]
    assert backlinks.count("<li>") == 2
    assert backlinks.count(">Linker</a>") == 1
    assert backlinks.count(">Other</a>") == 1
