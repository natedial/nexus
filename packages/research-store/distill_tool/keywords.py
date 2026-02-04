from __future__ import annotations

import json
import re
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


def load_dictionary(path: str | Path | None) -> list[str]:
    if not path:
        return []
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Dictionary not found: {path}")
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            terms = data.get("terms", [])
        else:
            terms = data
        return [str(term).strip() for term in terms if str(term).strip()]
    terms = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        terms.append(line)
    return terms


def extract_keywords(
    text: str,
    dictionary: list[str] | None = None,
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


def _dictionary_matches(text: str, dictionary: list[str]) -> Counter:
    counter: Counter = Counter()
    text_lower = text.lower()
    for term in dictionary:
        cleaned = term.strip().lower()
        if not cleaned:
            continue
        pattern = r"\b" + re.escape(cleaned).replace(r"\ ", r"\s+") + r"\b"
        count = len(re.findall(pattern, text_lower))
        if count:
            counter[cleaned] += count
    return counter


def _rake_keywords(text: str, max_phrases: int = 40) -> list[tuple[str, float]]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s\-]", " ", text)
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
