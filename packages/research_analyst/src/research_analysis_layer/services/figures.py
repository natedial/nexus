"""Chart citations copied onto an argument from parser figure records."""

from __future__ import annotations

from typing import Any


def figure_key_for_hash(content_hash: str) -> str:
    digest = content_hash.strip()
    return f"figure:{digest[:16]}" if digest else ""


def citation_from_figure(
    figure: dict[str, Any],
    *,
    document_id: str | None,
) -> dict[str, Any] | None:
    """Meal-sized figure record. Local image paths stay in the parser cache."""
    key = figure.get("figure_key")
    if not isinstance(key, str) or not key.strip():
        content_hash = figure.get("content_hash")
        if isinstance(content_hash, str):
            key = figure_key_for_hash(content_hash)
        else:
            key = ""
    if not key:
        return None
    bbox = figure.get("bbox")
    caption = figure.get("caption_text")
    if not isinstance(caption, str):
        caption = figure.get("caption") if isinstance(figure.get("caption"), str) else ""
    page = figure.get("page")
    label = figure.get("figure_id") or figure.get("label") or ""
    return {
        "figure_key": key.strip(),
        "label": str(label),
        "page": page if isinstance(page, int) else None,
        "bbox": list(bbox) if isinstance(bbox, list) else None,
        "caption": caption,
        "content_hash": str(figure.get("content_hash") or ""),
        "document_id": document_id or "",
    }


def figures_for_document(document: Any) -> dict[str, dict[str, Any]]:
    """Index citeable charts for one hydrated document, keyed by figure_key."""
    parsed = getattr(document, "document", None)
    document_id = None
    if parsed is not None:
        document_id = getattr(parsed, "document_id", None) or getattr(document, "file_id", None)
    else:
        document_id = getattr(document, "file_id", None)
    if document_id is not None:
        document_id = str(document_id)

    indexed: dict[str, dict[str, Any]] = {}
    artifacts = getattr(document, "artifacts", None)
    manifest = getattr(artifacts, "figure_manifest", None) or []
    if isinstance(manifest, list):
        for item in manifest:
            if not isinstance(item, dict):
                continue
            citation = citation_from_figure(item, document_id=document_id)
            if citation is not None:
                indexed[citation["figure_key"]] = citation

    for span in getattr(document, "spans", None) or []:
        metadata = getattr(span, "metadata", None) or {}
        if not isinstance(metadata, dict):
            continue
        citation = citation_from_figure(metadata, document_id=document_id)
        if citation is None or citation["figure_key"] in indexed:
            continue
        indexed[citation["figure_key"]] = citation
    return indexed
