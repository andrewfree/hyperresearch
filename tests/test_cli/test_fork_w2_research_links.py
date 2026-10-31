import pytest
from typer.testing import CliRunner

from hyperresearch.cli import app
from hyperresearch.cli.research import _extract_links_from_results
from hyperresearch.web.base import WebResult


@pytest.mark.parametrize("content,expected", [
    ("https://en.wikipedia.org/wiki/Mercury_(planet)", "https://en.wikipedia.org/wiki/Mercury_(planet)"),
    ("(https://en.wikipedia.org/wiki/Mercury_(planet)).", "https://en.wikipedia.org/wiki/Mercury_(planet)"),
    ("[Mercury](https://en.wikipedia.org/wiki/Mercury_(planet))", "https://en.wikipedia.org/wiki/Mercury_(planet)"),
    ("(https://example.org/a).,;:", "https://example.org/a"),
])
def test_research_links_preserve_balanced_parentheses(content, expected):
    result = WebResult(url="https://example.org", title="Page", content=content)
    assert _extract_links_from_results([result]) == [expected]


def test_research_depth_fetches_intact_url_and_literal_titles(tmp_vault, monkeypatch):
    url = "https://en.wikipedia.org/wiki/Mercury_(planet)"
    fetched = []

    class Provider:
        name = "offline"

        def search(self, query, max_results=5):
            return [WebResult(url="https://example.org/start", title="x[/y]", content=f"See [Mercury]({url}).\n" * 30)]

        def fetch(self, link):
            fetched.append(link)
            return WebResult(url=link, title="Mercury[/z]", content="Mercury is a planet. " * 50)

    monkeypatch.setattr("hyperresearch.cli.fetch._load_provider", lambda *args: Provider())
    monkeypatch.chdir(tmp_vault.root)
    result = CliRunner().invoke(app, ["research", "topic[/q]", "--depth", "1"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, repr(result.exception)
    assert fetched == [url]
    assert "topic[/q]" in result.output
    assert "x[/y]" in result.output
    assert "Mercury[/z]" in result.output
    assert "Synthesis:" in result.output
