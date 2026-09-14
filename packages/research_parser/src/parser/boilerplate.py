"""Deterministic boilerplate stripping for sell-side research PDFs."""

from functools import lru_cache
from pathlib import Path
import re

import structlog
import yaml

logger = structlog.get_logger()
RULES_PATH = Path(__file__).resolve().parents[2] / "config" / "boilerplate_rules.yaml"

_BOILERPLATE_HEADERS = [
    "appendix",
    "analyst certification",
    "analyst certifications",
    "analyst disclosure",
    "analyst disclosures",
    "analyst compensation",
    "analyst coverage",
    "important disclosure",
    "important disclosures",
    "important information",
    "important legal information",
    "important legal disclosures",
    "additional information",
    "disclosure",
    "disclosures",
    "other disclosures",
    "company-specific disclosures",
    "disclosures and disclaimers",
    "research disclosures",
    "legal disclaimer",
    "legal disclosure",
    "legal disclosures",
    "legal and regulatory disclosures",
    "regulatory and legal disclosures",
    "notices and disclaimers",
    "disclaimer",
    "disclaimers",
    "regulatory disclosure",
    "regulatory disclosures",
    "conflict of interest",
    "conflicts of interest",
    "company specific disclosures",
    "investor disclosures",
    "risk disclosures",
    "distribution",
    "copyright",
]

_LEGAL_MARKERS = [
    "analyst certification",
    "analyst certifications",
    "analyst disclosure",
    "analyst disclosures",
    "important disclosure",
    "important disclosures",
    "important legal",
    "conflict of interest",
    "conflicts of interest",
    "disclaimer",
    "disclosures and disclaimers",
    "regulatory",
    "distribution",
    "research analyst",
    "investment banking",
    "compensation",
    "rating history",
    "price target",
    "non us analyst disclosure",
    "us analyst disclosure",
    "copyright",
]


def strip_boilerplate(
    text: str,
    *,
    document_name: str | None = None,
    source_hint: str | None = None,
    log=None,
) -> str:
    """Remove trailing legal disclosures when a high-confidence header is found."""
    log = log or logger
    log.info("Stripping boilerplate", text_length=len(text))
    cleaned, match_info = _strip_boilerplate_deterministic(
        text,
        document_name=document_name,
        source_hint=source_hint,
    )
    if cleaned is not None:
        log.info(
            "Boilerplate stripped",
            original_length=len(text),
            result_length=len(cleaned),
            reduction=f"{(1 - len(cleaned) / len(text)) * 100:.1f}%",
            match_info=match_info,
        )
        return cleaned
    if match_info is not None:
        log.info(
            "Deterministic strip did not meet confidence thresholds",
            match_info=match_info,
        )
    return text


@lru_cache(maxsize=1)
def _load_rules() -> dict:
    if not RULES_PATH.exists():
        return {}
    with open(RULES_PATH) as handle:
        return yaml.safe_load(handle) or {}


def _infer_source_key(
    rules: dict,
    text: str,
    document_name: str | None = None,
    source_hint: str | None = None,
) -> str | None:
    sources = rules.get("sources", {})
    if source_hint:
        hint = source_hint.strip().lower()
        if hint in sources:
            return hint

    file_haystack = (document_name or "").lower()
    text_haystack = text[:6000].lower()
    for key, cfg in sources.items():
        aliases = [alias.lower() for alias in cfg.get("aliases", [])]
        if any(alias and alias in file_haystack for alias in aliases):
            return key
        if any(alias and alias in text_haystack for alias in aliases):
            return key
    return None


def _profile_for_source(rules: dict, source_key: str | None) -> dict:
    defaults = rules.get("defaults", {})
    source_cfg = rules.get("sources", {}).get(source_key or "", {})
    headers = list(
        dict.fromkeys(defaults.get("headers", _BOILERPLATE_HEADERS) + source_cfg.get("headers", []))
    )
    markers = list(
        dict.fromkeys(defaults.get("markers", _LEGAL_MARKERS) + source_cfg.get("markers", []))
    )
    return {
        "source_key": source_key,
        "headers": [header.lower().strip() for header in headers if header],
        "markers": [marker.lower().strip() for marker in markers if marker],
        "min_fraction": source_cfg.get("min_fraction", defaults.get("min_fraction", 0.7)),
        "density_window_lines": source_cfg.get(
            "density_window_lines",
            defaults.get("density_window_lines", 40),
        ),
        "min_density": source_cfg.get("min_density", defaults.get("min_density", 0.12)),
        "min_hits": source_cfg.get("min_hits", defaults.get("min_hits", 3)),
        "max_strip_fraction": source_cfg.get(
            "max_strip_fraction",
            defaults.get("max_strip_fraction", 0.40),
        ),
    }


def _is_parser_noise(line: str) -> bool:
    lower = line.lower()
    if "data:image/" in lower:
        return True
    if "<bound method" in lower:
        return True
    if lower.startswith("![figure") and "pictureitem" in lower:
        return True
    return False


def _normalize_candidate(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    candidate = stripped
    if ":" in stripped:
        head = stripped.split(":", 1)[0]
        if head and len(head) <= 120:
            candidate = head
    candidate = re.sub(r"^#+\s*", "", candidate)
    return re.sub(r"^[\W_]*(\d+(\.\d+)*)\s+|[\s\-:]+$", "", candidate).lower()


def _legal_density(
    lines: list[str],
    start_idx: int,
    markers: list[str],
    window_lines: int,
) -> tuple[float, int]:
    end_idx = min(len(lines), start_idx + max(window_lines, 1))
    window = lines[start_idx:end_idx]
    hits = 0
    for raw in window:
        lower = raw.lower()
        if any(marker in lower for marker in markers):
            hits += 1
    return hits / max(len(window), 1), hits


def _classify_confidence(
    density: float,
    hits: int,
    line_fraction: float,
    min_density: float,
    min_hits: int,
) -> str:
    strong_density = density >= (min_density * 1.8)
    strong_hits = hits >= (min_hits * 2)
    late_in_doc = line_fraction >= 0.8
    if strong_density and strong_hits and late_in_doc:
        return "high"
    if density >= min_density and hits >= min_hits:
        return "medium"
    return "low"


def _strip_boilerplate_deterministic(
    text: str,
    document_name: str | None = None,
    source_hint: str | None = None,
) -> tuple[str | None, dict | None]:
    lines = text.splitlines()
    total_lines = max(len(lines), 1)
    rules = _load_rules()
    source_key = _infer_source_key(
        rules=rules,
        text=text,
        document_name=document_name,
        source_hint=source_hint,
    )
    profile = _profile_for_source(rules, source_key)
    headers = profile["headers"] or _BOILERPLATE_HEADERS
    markers = profile["markers"] or _LEGAL_MARKERS
    min_fraction = profile["min_fraction"]
    min_density = profile["min_density"]
    min_hits = profile["min_hits"]
    max_strip_fraction = profile["max_strip_fraction"]
    density_window_lines = profile["density_window_lines"]

    first_early_match: dict | None = None
    best_rejected_match: dict | None = None
    for idx, line in enumerate(lines):
        if _is_parser_noise(line):
            continue
        stripped = line.strip()
        if not stripped:
            continue
        candidate = _normalize_candidate(stripped)
        if len(candidate) > 120:
            continue
        for header in headers:
            if candidate == header or re.match(rf"^{re.escape(header)}(\s|$)", candidate):
                line_fraction = idx / total_lines
                match_info = {
                    "line_index": idx + 1,
                    "total_lines": total_lines,
                    "line": stripped,
                    "source_key": source_key,
                    "header": header,
                }
                if line_fraction >= min_fraction:
                    density, hits = _legal_density(
                        lines=lines,
                        start_idx=idx,
                        markers=markers,
                        window_lines=density_window_lines,
                    )
                    confidence = _classify_confidence(
                        density=density,
                        hits=hits,
                        line_fraction=line_fraction,
                        min_density=min_density,
                        min_hits=min_hits,
                    )
                    candidate_info = {
                        **match_info,
                        "legal_density": round(density, 4),
                        "legal_hits": hits,
                        "line_fraction": round(line_fraction, 4),
                        "confidence": confidence,
                    }
                    if density >= min_density and hits >= min_hits:
                        cleaned = "\n".join(lines[:idx]).rstrip()
                        reduction = 1 - (len(cleaned) / max(len(text), 1))
                        if reduction > max_strip_fraction and confidence != "high":
                            candidate_info["reason"] = "strip_too_large"
                            candidate_info["strip_fraction"] = round(reduction, 4)
                            if (
                                best_rejected_match is None
                                or candidate_info["legal_density"]
                                > best_rejected_match["legal_density"]
                            ):
                                best_rejected_match = candidate_info
                            break
                        return cleaned, candidate_info
                    candidate_info["reason"] = "low_legal_density"
                    if (
                        best_rejected_match is None
                        or candidate_info["legal_density"] > best_rejected_match["legal_density"]
                    ):
                        best_rejected_match = candidate_info
                if first_early_match is None:
                    first_early_match = {
                        **match_info,
                        "reason": "header_too_early",
                        "line_fraction": round(line_fraction, 4),
                    }
                break
    if best_rejected_match is not None:
        return None, best_rejected_match
    return None, first_early_match
