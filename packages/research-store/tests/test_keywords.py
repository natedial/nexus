from __future__ import annotations

from distill_tool.keywords import DictionaryEntry, extract_keywords, normalize_term


def test_normalize_term_strips_diacritics_and_entities() -> None:
    assert normalize_term("Autorité &#x26; Régulation") == "autorite and regulation"


def test_extract_keywords_merges_dictionary_aliases_into_canonical_term() -> None:
    keywords = extract_keywords(
        "The FCA and the Financial Conduct Authority both appear in this paragraph.",
        dictionary=[DictionaryEntry(term="financial conduct authority", aliases=("fca",))],
        max_keywords=5,
    )

    assert keywords[0].term == "financial conduct authority"
    assert keywords[0].score == 2.0
