from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum


class AttachmentDecision(str, Enum):
    ALLOW = "allow"
    SKIP = "skip"
    QUARANTINE = "quarantine"


@dataclass(frozen=True)
class AttachmentPolicy:
    max_individual_bytes: int
    max_combined_bytes: int
    blocked_extensions: tuple[str, ...]
    allowed_extensions: tuple[str, ...]
    on_prohibited: str
    private_address: str


@dataclass(frozen=True)
class AttachmentResult:
    action: AttachmentDecision
    reason: str
    safe_filename: str
    payload: bytes
    content_type: str


_UNSAFE = re.compile(r"[<>:\"|?*\x00-\x1f]")


def sanitize_filename(
    name: str,
    private_address: str,
    used: set[str] | None = None,
) -> str:
    from research_relay.redact import redact_filename

    raw = redact_filename(name or "", private_address)
    raw = unicodedata.normalize("NFKC", raw)
    raw = raw.replace("\\", "/").replace("\x00", "")
    raw = os.path.basename(raw)
    raw = raw.replace("..", "")
    raw = _UNSAFE.sub("_", raw).strip().strip(".")
    if not raw:
        raw = "attachment"
    if len(raw) > 180:
        stem, ext = os.path.splitext(raw)
        raw = stem[: 180 - len(ext)] + ext
    if used is None:
        return raw
    candidate = raw
    stem, ext = os.path.splitext(raw)
    index = 2
    used_lower = {item.lower() for item in used}
    while candidate.lower() in used_lower:
        candidate = f"{stem}-{index}{ext}"
        index += 1
    used.add(candidate)
    return candidate


def _extension(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def evaluate_attachment(
    *,
    filename: str,
    payload: bytes,
    content_type: str,
    used_bytes: int,
    policy: AttachmentPolicy,
    used_names: set[str] | None = None,
) -> AttachmentResult:
    safe_name = sanitize_filename(filename, policy.private_address, used=used_names)
    ext = _extension(safe_name)
    prohibited = False
    reason = ""

    if policy.allowed_extensions:
        allowed = {item.lower() if item.startswith(".") else f".{item.lower()}" for item in policy.allowed_extensions}
        if ext not in allowed:
            prohibited = True
            reason = f"extension {ext or '[none]'} is not on the allow list"

    blocked = {item.lower() if item.startswith(".") else f".{item.lower()}" for item in policy.blocked_extensions}
    if ext in blocked:
        prohibited = True
        reason = f"extension {ext} is blocked"

    size = len(payload or b"")
    if size > policy.max_individual_bytes:
        prohibited = True
        reason = f"individual size {size} exceeds limit"
    elif used_bytes + size > policy.max_combined_bytes:
        prohibited = True
        reason = f"combined size {used_bytes + size} exceeds limit"

    if prohibited:
        action = (
            AttachmentDecision.QUARANTINE
            if policy.on_prohibited == "quarantine"
            else AttachmentDecision.SKIP
        )
        return AttachmentResult(
            action=action,
            reason=reason,
            safe_filename=safe_name,
            payload=payload,
            content_type=content_type or "application/octet-stream",
        )
    return AttachmentResult(
        action=AttachmentDecision.ALLOW,
        reason="",
        safe_filename=safe_name,
        payload=payload,
        content_type=content_type or "application/octet-stream",
    )
