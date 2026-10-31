"""Only actual duplicate URLs receive the duplicate error code."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from hyperresearch.core.fetcher import prepare_fetch
from hyperresearch.core.note import write_note
from hyperresearch.core.vault import Vault


@pytest.mark.parametrize("failure", ["unknown_provider", "fetch_value_error"])
def test_other_value_errors_are_fetch_errors(tmp_vault, monkeypatch, failure):
    server = pytest.importorskip("hyperresearch.mcp.server")
    if failure == "fetch_value_error":
        def fetch(url):
            raise ValueError("Invalid fetched content")
        monkeypatch.setattr("hyperresearch.web.base.get_provider",
                            lambda *a, **kw: SimpleNamespace(fetch=fetch))

    def call():
        vault = Vault(tmp_vault.root)
        monkeypatch.setattr(server, "_vault", vault)
        try:
            return json.loads(asyncio.run(server.fetch_url("https://example.com/", provider="nope")))
        finally:
            vault.close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        data = pool.submit(call).result()
    assert data["ok"] is False
    assert data["error_code"] == "FETCH_ERROR"
    assert ("Unknown web provider" if failure == "unknown_provider" else "Invalid fetched content") in data["error"]


def test_duplicate_is_a_specific_value_error(tmp_vault):
    write_note(tmp_vault.notes_dir, "Existing")
    tmp_vault.auto_sync()
    tmp_vault.db.execute(
        "INSERT INTO sources (url, note_id, domain, fetched_at, provider) VALUES (?, ?, ?, ?, ?)",
        ("https://example.com/", "existing", "example.com", "2026-01-01", "builtin"),
    )
    tmp_vault.db.commit()
    with pytest.raises(ValueError, match="already fetched") as exc:
        prepare_fetch(tmp_vault, "https://example.com/", provider_name="nope")
    assert type(exc.value).__name__ == "DuplicateURLError"
