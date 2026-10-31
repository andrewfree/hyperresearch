"""A Sources URL that ends in its own `)` must still resolve to its note.

parse_sources_section trimmed every trailing `.`, `,` and `)` from the URL it
found in a Sources entry, to drop the punctuation around a link written as
`(https://...)` or at the end of a sentence. That also cut the closing paren
off URLs such as https://en.wikipedia.org/wiki/Mercury_(planet), so the exact
URL lookup missed, and a citation to a note saved from that page was flagged
dangling. Only a `)` the URL never opened is punctuation.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.core.citecheck import extract_pairs, parse_sources_section, triage_pairs
from hyperresearch.core.note import write_note
from hyperresearch.core.sync import compute_sync_plan, execute_sync

MERCURY = "https://en.wikipedia.org/wiki/Mercury_(planet)"
VENUS = "https://en.wikipedia.org/wiki/Venus"


@pytest.fixture
def planet_vault(tmp_vault):
    # Titles differ from the Sources entries' titles, so only the URL resolves.
    write_note(tmp_vault.notes_dir, "Mercury (planet) - Wikipedia", body="Mercury is first.",
               source=MERCURY)
    write_note(tmp_vault.notes_dir, "Venus - Wikipedia", body="Venus is second.", source=VENUS)
    execute_sync(tmp_vault, compute_sync_plan(tmp_vault, force=True))
    return tmp_vault


def _sources(entry: str) -> str:
    return f"Mercury orbits closest [1].\n\n## Sources\n\n[1] {entry}\n"


@pytest.mark.parametrize(
    "entry",
    [
        f"Mercury (planet). {MERCURY}",
        f"Mercury (planet). {MERCURY}.",
        f"Mercury (planet), {MERCURY},",
        f"Mercury (planet) ({MERCURY})",
        f"Mercury (planet) ({MERCURY}).",
        f"[Mercury (planet)]({MERCURY})",
    ],
    ids=["bare", "full-stop", "comma", "in-parens", "in-parens-full-stop", "markdown-link"],
)
def test_url_with_its_own_closing_paren_resolves(planet_vault, entry):
    assert parse_sources_section(_sources(entry), planet_vault.db) == {"1": "mercury-planet-wikipedia"}


@pytest.mark.parametrize(
    "entry",
    [f"Venus ({VENUS})", f"Venus ({VENUS}).", f"[Venus]({VENUS})", f"Venus. {VENUS}),"],
    ids=["in-parens", "in-parens-full-stop", "markdown-link", "stray-paren"],
)
def test_paren_the_url_never_opened_is_still_trimmed(planet_vault, entry):
    assert parse_sources_section(_sources(entry), planet_vault.db) == {"1": "venus-wikipedia"}


def test_citation_to_a_parenthesised_url_is_not_dangling(planet_vault):
    report = (
        "# R\n\nMercury orbits closest to the sun [1]. Venus is the hottest planet [2].\n\n"
        f"## Sources\n\n[1] Mercury (planet). {MERCURY}\n[2] Venus. {VENUS}\n"
    )
    triaged = triage_pairs(extract_pairs(report, planet_vault.db), planet_vault.db)
    assert triaged["dangling"] == 0
    assert [p["note_id"] for p in triaged["pairs"]] == ["mercury-planet-wikipedia", "venus-wikipedia"]


def test_citecheck_extract_reports_no_dangling_citation(planet_vault, monkeypatch):
    monkeypatch.chdir(planet_vault.root)
    report = (
        "# R\n\nMercury orbits closest to the sun [1]. Venus is the hottest planet [2].\n\n"
        f"## Sources\n\n[1] Mercury (planet). {MERCURY}\n[2] Venus. {VENUS}\n"
    )
    (planet_vault.notes_dir / "final_report_cp-dddddd.md").write_text(report, encoding="utf-8")
    result = CliRunner().invoke(app, ["citecheck", "extract", "cp-dddddd", "--json"])
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)["data"]["summary"]
    assert summary["dangling"] == 0
    assert summary["total"] == 2
