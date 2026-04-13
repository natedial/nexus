"""Deterministic assertion extraction."""

from __future__ import annotations

import re

from research_analysis_layer.models import AnalysisChunkDraft, AssertionDraft, EvidenceUnitDraft
from research_analysis_layer.models.assertion_models import normalize_text


class AssertionExtractor:
    """Create one or more structured assertions from a chunk."""

    _CHUNK_TO_ASSERTION_TYPE = {
        "forecast_block": "forecast",
        "market_view": "interpretation",
        "data_interpretation": "observation",
        "risk_scenario": "risk_condition",
        "policy_view": "policy_claim",
        "trade_rationale": "trade_claim",
    }

    _FORECAST_MARKERS = ("expect", "forecast", "project", "likely", "unlikely", "will", "should")
    _CAUSAL_MARKERS = (
        "because",
        "due to",
        "driven by",
        "drives",
        "leads to",
        "lead to",
        "boost",
        "weigh on",
    )
    _RISK_MARKERS = ("if ", "unless", "risk", "scenario", "could", "may")
    _QUESTION_MARKERS = ("?", "whether", "unclear", "open question", "remains to be seen")
    _POSITIVE_MARKERS = ("rise", "increase", "stronger", "higher", "improve", "upside")
    _NEGATIVE_MARKERS = ("fall", "decline", "weaker", "lower", "downside", "less likely")

    def extract(
        self,
        chunk: AnalysisChunkDraft,
        evidence: list[EvidenceUnitDraft],
    ) -> list[AssertionDraft]:
        if not evidence:
            return []

        candidate_sentences = self._candidate_sentences(chunk, evidence)
        assertions: list[AssertionDraft] = []
        seen_normalized: set[str] = set()
        default_type = self._CHUNK_TO_ASSERTION_TYPE.get(chunk.chunk_type, "observation")

        for order, sentence in enumerate(candidate_sentences, start=1):
            normalized = normalize_text(sentence)
            if not normalized or normalized in seen_normalized:
                continue
            seen_normalized.add(normalized)
            assertion_type = self._classify_assertion_type(sentence, default_type)
            summary = self._summary_text(chunk.title, sentence)
            text = sentence
            if chunk.title.strip() and normalize_text(chunk.title) not in normalized:
                text = f"{chunk.title.strip()}: {sentence}"
            condition_text = self._extract_condition(sentence)
            qualifier_text = self._extract_qualifier(sentence)
            subject_text, object_text = self._extract_subject_object(chunk.title, sentence, assertion_type)
            assertions.append(
                AssertionDraft(
                    chunk_order=chunk.chunk_order,
                    assertion_order=len(assertions) + 1,
                    assertion_type=assertion_type,
                    text=text,
                    normalized_text=normalize_text(text),
                    summary_text=summary,
                    polarity=self._polarity(sentence),
                    confidence_label=self._confidence_label(sentence, assertion_type),
                    extraction_confidence="high" if self._looks_precise(sentence) else "medium",
                    time_horizon=self._time_horizon(sentence, assertion_type),
                    time_anchor=self._extract_time_anchor(sentence),
                    condition_text=condition_text,
                    qualifier_text=qualifier_text,
                    subject_text=subject_text,
                    object_text=object_text,
                )
            )
        if assertions:
            return assertions

        fallback_text = chunk.text.strip() or chunk.title.strip()
        normalized = normalize_text(fallback_text)
        return [
            AssertionDraft(
                chunk_order=chunk.chunk_order,
                assertion_order=1,
                assertion_type=default_type,
                text=fallback_text,
                normalized_text=normalized,
                summary_text=chunk.title.strip() or fallback_text,
                confidence_label=self._confidence_label(fallback_text, default_type),
                extraction_confidence="medium",
                time_horizon=self._time_horizon(fallback_text, default_type),
                subject_text=chunk.title.strip() or fallback_text,
            )
        ]

    def _candidate_sentences(
        self,
        chunk: AnalysisChunkDraft,
        evidence: list[EvidenceUnitDraft],
    ) -> list[str]:
        ordered_text = [chunk.text.strip()]
        ordered_text.extend(
            item.text.strip()
            for item in evidence
            if item.evidence_type in {"theme_context", "excerpt", "raw_text_fallback"} and item.text.strip()
        )
        sentences: list[str] = []
        for text in ordered_text:
            parts = re.split(r"(?<=[.!?])\s+|\s*;\s*", text)
            for part in parts:
                cleaned = part.strip(" -")
                if len(cleaned) >= 20:
                    sentences.append(cleaned)
        return sentences[:5]

    def _classify_assertion_type(self, sentence: str, default_type: str) -> str:
        lowered = sentence.lower()
        if any(marker in lowered for marker in self._QUESTION_MARKERS):
            return "open_question"
        if any(marker in lowered for marker in self._CAUSAL_MARKERS):
            if any(token in lowered for token in ("market", "spread", "yield", "equity", "dollar", "fx")):
                return "market_impact"
            return "causal_claim"
        if default_type == "forecast" or any(marker in lowered for marker in self._FORECAST_MARKERS):
            return "forecast"
        if any(marker in lowered for marker in self._RISK_MARKERS):
            return "risk_condition"
        return default_type

    @staticmethod
    def _summary_text(title: str, sentence: str) -> str:
        sentence = sentence.strip()
        if title.strip() and normalize_text(title) in normalize_text(sentence):
            return title.strip()
        return sentence[:100].rstrip(".")

    @classmethod
    def _extract_subject_object(
        cls,
        title: str,
        sentence: str,
        assertion_type: str,
    ) -> tuple[str | None, str | None]:
        lowered = sentence.lower()
        if assertion_type in {"causal_claim", "market_impact"}:
            for marker in cls._CAUSAL_MARKERS:
                idx = lowered.find(marker)
                if idx > 0:
                    subject = sentence[:idx].strip(" ,:-")
                    obj = sentence[idx + len(marker):].strip(" ,:-.")
                    return subject or title.strip() or None, obj or None
        if assertion_type == "risk_condition":
            if lowered.startswith("if "):
                after_if = sentence[3:]
                if "," in after_if:
                    condition, outcome = after_if.split(",", 1)
                    return outcome.strip(" ,:-.") or title.strip() or None, condition.strip(" ,:-.") or None
            return title.strip() or sentence[:80], None
        if assertion_type == "forecast":
            if ":" in sentence:
                subject, outcome = sentence.split(":", 1)
                return subject.strip() or title.strip() or None, outcome.strip() or None
            return title.strip() or sentence[:80], None
        if assertion_type == "open_question":
            return None, sentence.strip()
        return title.strip() or sentence[:80], None

    @staticmethod
    def _extract_condition(sentence: str) -> str | None:
        match = re.search(r"\b(if|unless|assuming|provided that)\b(.+)", sentence, re.IGNORECASE)
        if not match:
            return None
        return match.group(0).strip().rstrip(".")

    @staticmethod
    def _extract_qualifier(sentence: str) -> str | None:
        match = re.search(
            r"\b(base case|likely|unlikely|consensus|contrarian|tentative|probable|possible)\b",
            sentence,
            re.IGNORECASE,
        )
        if match:
            return match.group(1).lower()
        return None

    @classmethod
    def _polarity(cls, sentence: str) -> str:
        lowered = sentence.lower()
        if any(marker in lowered for marker in cls._NEGATIVE_MARKERS):
            return "negative"
        if any(marker in lowered for marker in cls._POSITIVE_MARKERS):
            return "positive"
        return "mixed" if " but " in lowered else "not_applicable"

    @classmethod
    def _confidence_label(cls, sentence: str, assertion_type: str) -> str:
        lowered = sentence.lower()
        if assertion_type == "forecast" and cls._looks_precise(sentence):
            return "high"
        if any(token in lowered for token in ("may", "could", "possible", "unclear")):
            return "low"
        return "medium"

    @staticmethod
    def _looks_precise(sentence: str) -> bool:
        return bool(re.search(r"\d", sentence)) or "%" in sentence

    @classmethod
    def _time_horizon(cls, sentence: str, assertion_type: str) -> str:
        lowered = sentence.lower()
        if assertion_type == "forecast":
            return "forward"
        if any(token in lowered for token in ("next", "ahead", "by year-end", "into", "over coming")):
            return "forward"
        if any(token in lowered for token in ("was", "were", "rose", "fell", "printed")):
            return "historical"
        return "current"

    @staticmethod
    def _extract_time_anchor(sentence: str) -> str | None:
        match = re.search(
            r"\b("
            r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
            r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?"
            r")(?:\s+\d{1,2}(?:,\s*\d{4})?|\s+\d{4})?\b",
            sentence,
            re.IGNORECASE,
        )
        if match:
            return match.group(0)
        return None
