"""Select a parser backend using confidence-aware fallback."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

import structlog

from .backend import (
    ConfidenceResult,
    FigureRecord,
    ParserBackend,
    TextParseResult,
)

logger = structlog.get_logger()

_ACCEPTABLE_STATUS = {"PASS", "REPAIR"}


@dataclass
class ParsedDocument:
    backend_name: str
    text_result: TextParseResult
    figures: list[FigureRecord]
    confidence: ConfidenceResult
    ocr_retried: bool = False
    ocr_retry_reasons: list[str] = field(default_factory=list)


def parse_with_fallback(
    backends: list[tuple[str, ParserBackend]],
    pdf_path: Path,
    log=None,
) -> ParsedDocument:
    """Try parser backends in order until one produces PASS or REPAIR.

    FALLBACK results are kept as candidates. If every successful parse is
    FALLBACK, the highest-scoring candidate is returned. Parse exceptions skip
    that backend. If every backend fails, a RuntimeError is raised.
    """
    log = log or logger
    if not backends:
        raise ValueError("No parser backends configured")

    attempts: list[ParsedDocument] = []
    errors: list[str] = []

    for backend_name, backend in backends:
        try:
            log.info("Parsing PDF", backend=backend_name)
            text_result = backend.parse_text(pdf_path)
            figures = backend.extract_figures(pdf_path)
            confidence = backend.confidence(text_result.blocks, figures)
            parsed = ParsedDocument(
                backend_name=backend_name,
                text_result=text_result,
                figures=figures,
                confidence=confidence,
            )
            attempts.append(parsed)
            log.info(
                "Parse confidence",
                backend=backend_name,
                score=confidence.score,
                status=confidence.status,
                reasons=confidence.reasons,
                block_count=len(text_result.blocks),
                figure_count=len(figures),
            )
            if confidence.status in _ACCEPTABLE_STATUS:
                return parsed
            log.info(
                "Parse quality below threshold, trying next backend",
                backend=backend_name,
                status=confidence.status,
            )
        except Exception as exc:
            message = f"{backend_name}: {exc}"
            errors.append(message)
            log.warning("Parse backend failed, falling back", backend=backend_name, error=str(exc))

    if attempts:
        attempts.sort(key=lambda item: item.confidence.score, reverse=True)
        selected = attempts[0]
        log.warning(
            "All parser backends returned FALLBACK; using highest score",
            backend=selected.backend_name,
            score=selected.confidence.score,
            attempted=[item.backend_name for item in attempts],
        )
        return selected

    raise RuntimeError("Parse failed: " + "; ".join(errors))


def parse_with_optional_ocr(
    *,
    digital_backend: ParserBackend,
    ocr_backend: ParserBackend | None = None,
    ocr_backend_factory=None,
    mineru_backend: ParserBackend | None = None,
    pdf_path: Path,
    log=None,
    ocr_retry: bool = True,
) -> ParsedDocument:
    """Digital Docling first; OCR only when the first pass looks thin or gappy."""
    from .quality import ocr_retry_reasons, prefer_parse

    log = log or logger
    parsed: ParsedDocument | None = None
    digital_error: RuntimeError | None = None
    try:
        parsed = parse_with_fallback([("docling", digital_backend)], pdf_path, log)
    except RuntimeError as exc:
        digital_error = exc
        log.warning("Digital parse failed", error=str(exc))

    reasons: list[str] = []
    if parsed is None:
        reasons = ["digital_parse_failed"]
    elif ocr_retry:
        reasons = ocr_retry_reasons(parsed)

    ocr = ocr_backend
    if reasons and ocr is None and ocr_backend_factory is not None:
        ocr = ocr_backend_factory()

    ocr_retried = False
    if reasons and ocr is not None:
        log.info(
            "Retrying parse with OCR",
            reasons=reasons,
            status=parsed.confidence.status if parsed is not None else None,
        )
        try:
            ocr_parsed = parse_with_fallback([("docling-ocr", ocr)], pdf_path, log)
            ocr_retried = True
            if parsed is None:
                parsed = ocr_parsed
            else:
                parsed = prefer_parse(parsed, ocr_parsed)
        except RuntimeError as exc:
            log.warning("OCR retry failed", error=str(exc), reasons=reasons)
            if parsed is None:
                raise digital_error from exc

    if parsed is None:
        if digital_error is not None:
            raise digital_error
        raise RuntimeError("Parse failed: no digital or OCR result")

    parsed = replace(parsed, ocr_retried=ocr_retried, ocr_retry_reasons=reasons)

    if parsed.confidence.status == "FALLBACK" and mineru_backend is not None:
        try:
            mineru_parsed = parse_with_fallback([("mineru", mineru_backend)], pdf_path, log)
            chosen = prefer_parse(parsed, mineru_parsed)
            parsed = replace(
                chosen,
                ocr_retried=parsed.ocr_retried,
                ocr_retry_reasons=parsed.ocr_retry_reasons,
            )
        except RuntimeError as exc:
            log.warning("MinerU fallback failed", error=str(exc))

    return parsed
