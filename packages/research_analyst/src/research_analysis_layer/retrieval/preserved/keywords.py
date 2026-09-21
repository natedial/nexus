# Preserved from packages/research-store/distill_tool/keywords.py (Phase 1).
# Reference only — not imported.
from __future__ import annotations

import html
import json
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "he",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "that",
    "the",
    "to",
    "was",
    "were",
    "will",
    "with",
}


@dataclass(frozen=True)
class Keyword:
    term: str
    source: str
    score: float


@dataclass(frozen=True)
class DictionaryEntry:
    term: str
    aliases: tuple[str, ...] = ()


def normalize_term(text: str) -> str:
    text = html.unescape(text or "")
    text = text.replace("&", " and ")
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"['’]", "", text)
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_dictionary(path: str | Path | None) -> list[DictionaryEntry]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dictionary not found: {path}")
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            terms = data.get("terms", data.get("entries", []))
        else:
            terms = data
        return _parse_dictionary_entries(terms)
    terms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    return _parse_dictionary_entries(terms)


def extract_keywords(
    text: str,
    dictionary: list[str] | list[DictionaryEntry] | None = None,
    max_keywords: int = 20,
) -> list[Keyword]:
    dictionary = dictionary or []
    matches = _dictionary_matches(text, dictionary)
    rake_terms = _rake_keywords(text)

    keywords: list[Keyword] = []
    for term, count in matches.most_common():
        keywords.append(Keyword(term=term, source="dictionary", score=float(count)))
    for term, score in rake_terms:
        if len(keywords) >= max_keywords:
            break
        if term in matches:
            continue
        keywords.append(Keyword(term=term, source="rake", score=score))

    return keywords[:max_keywords]


def _dictionary_matches(text: str, dictionary: list[str] | list[DictionaryEntry]) -> Counter:
    counter: Counter = Counter()
    text_normalized = normalize_term(text)
    for entry in _coerce_dictionary_entries(dictionary):
        canonical = normalize_term(entry.term)
        if not canonical:
            continue
        total = 0
        variants = {canonical, *(normalize_term(alias) for alias in entry.aliases)}
        for variant in variants:
            if not variant:
                continue
            pattern = r"\b" + re.escape(variant).replace(r"\ ", r"\s+") + r"\b"
            total += len(re.findall(pattern, text_normalized))
        if total:
            counter[canonical] += total
    return counter


def _rake_keywords(text: str, max_phrases: int = 40) -> list[tuple[str, float]]:
    text = normalize_term(text)
    words = [w for w in text.split() if w]

    phrases: list[list[str]] = []
    current: list[str] = []
    for word in words:
        if word in STOPWORDS:
            if current:
                phrases.append(current)
                current = []
            continue
        current.append(word)
    if current:
        phrases.append(current)

    word_freq: Counter = Counter()
    word_degree: Counter = Counter()
    for phrase in phrases:
        degree = len(phrase) - 1
        for word in phrase:
            word_freq[word] += 1
            word_degree[word] += degree

    word_score = {
        word: (word_degree[word] + word_freq[word]) / word_freq[word]
        for word in word_freq
    }

    phrase_scores: dict[str, float] = {}
    for phrase in phrases:
        if not phrase:
            continue
        key = " ".join(phrase)
        score = sum(word_score[word] for word in phrase)
        phrase_scores[key] = max(score, phrase_scores.get(key, 0.0))

    ranked = sorted(phrase_scores.items(), key=lambda item: item[1], reverse=True)
    return ranked[:max_phrases]


def _coerce_dictionary_entries(
    dictionary: list[str] | list[DictionaryEntry],
) -> list[DictionaryEntry]:
    entries: list[DictionaryEntry] = []
    for item in dictionary:
        if isinstance(item, DictionaryEntry):
            entries.append(item)
            continue
        parsed = _parse_dictionary_entry(item)
        if parsed is not None:
            entries.append(parsed)
    return entries


def _parse_dictionary_entries(items: list[object]) -> list[DictionaryEntry]:
    entries: list[DictionaryEntry] = []
    for item in items:
        parsed = _parse_dictionary_entry(item)
        if parsed is not None:
            entries.append(parsed)
    return entries


def _parse_dictionary_entry(item: object) -> DictionaryEntry | None:
    if isinstance(item, dict):
        raw_term = str(item.get("term", "")).strip()
        if not raw_term:
            return None
        aliases = tuple(
            normalized
            for normalized in (normalize_term(str(alias)) for alias in item.get("aliases", []))
            if normalized and normalized != normalize_term(raw_term)
        )
        return DictionaryEntry(term=normalize_term(raw_term), aliases=aliases)

    raw = str(item).strip()
    if not raw:
        return None
    parts = [normalize_term(part) for part in raw.split("|")]
    parts = [part for part in parts if part]
    if not parts:
        return None
    canonical = parts[0]
    aliases = tuple(alias for alias in parts[1:] if alias != canonical)
    return DictionaryEntry(term=canonical, aliases=aliases)
