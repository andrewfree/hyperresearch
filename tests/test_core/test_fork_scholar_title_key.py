# ruff: noqa: RUF001
# RUF001 flags Cyrillic and Greek letters as ASCII lookalikes; they are the point here.
"""title_key keeps non-Latin letters, so distinct works stay distinct.

title_key folded accents and then deleted everything outside [a-z0-9], which
deleted every Cyrillic and CJK letter too. Two different Russian COVID-19
papers both became "covid19", two Chinese BERT papers both became "bert", and
merge_papers clustered them whenever a DOI was missing: one work vanished and
its citation count was grafted onto the other.
"""

from __future__ import annotations

from hyperresearch.scholar.base import Paper, title_key
from hyperresearch.scholar.dedup import merge_papers

RU_1 = "Влияние COVID-19 на экономику России"
RU_2 = "COVID-19 у детей: клинические особенности"
ZH_1 = "BERT模型在文本分类中的应用"
ZH_2 = "基于BERT模型的命名实体识别"


def test_distinct_non_latin_titles_get_distinct_keys():
    assert title_key(RU_1) != title_key(RU_2)
    assert title_key(ZH_1) != title_key(ZH_2)
    assert title_key("α-synuclein aggregation") != title_key("β-synuclein aggregation")


def test_the_same_non_latin_title_still_matches_across_spellings():
    assert title_key(RU_1) == title_key("влияние covid-19 на экономику россии.")
    assert title_key(ZH_1) == title_key("BERT模型在文本分类中的应用。")


def test_latin_folding_is_unchanged():
    assert title_key("Attention Is All You Need") == "attentionisallyouneed"
    assert title_key("Café Crème: a study.") == title_key("cafe creme - A Study")
    assert title_key("Naïve Bayes") == "naivebayes"


def test_merge_keeps_two_distinct_cyrillic_works_apart():
    a = Paper(title=RU_1, source="openalex", year=2022, citation_count=5)
    b = Paper(title=RU_2, source="openalex", year=2022, citation_count=6)
    merged = merge_papers([a, b], ["openalex"])
    assert sorted(p.title for p in merged) == sorted([RU_1, RU_2])
    assert {p.citation_count for p in merged} == {5, 6}


def test_merge_still_joins_one_cjk_work_seen_by_two_providers():
    a = Paper(title=ZH_1, source="openalex", year=2021, doi="10.1/zh")
    b = Paper(title=ZH_1 + "。", source="crossref", year=2021)
    merged = merge_papers([a, b], ["openalex", "crossref"])
    assert len(merged) == 1
