"""Literal control characters in markdown are not viewer highlights."""

import pytest

from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync
from hyperresearch.serve.server import HyperresearchHandler


@pytest.mark.parametrize("long_body", [False, True])
def test_control_characters_do_not_forge_highlights(tmp_vault, long_body):
    body = "Literal \x02prefix and \x03suffix precede widget."
    if long_body:
        body += " filler" * 3000
    write_note(tmp_vault.notes_dir, "Control text", body=body)
    result = execute_sync(tmp_vault, compute_sync_plan(tmp_vault))
    assert not result.errors
    handler = object.__new__(HyperresearchHandler)
    handler._db = tmp_vault.db
    responses = []
    handler._send = lambda *args: responses.append(args)

    handler._serve_search("widget")

    page = responses[0][1]
    assert "\x02prefix and \x03suffix" in page
    assert page.count("<mark>") == page.count("</mark>") == 1
    assert "<mark>widget</mark>" in page
