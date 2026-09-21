from __future__ import annotations

import hashlib

from research_relay.intake_contract import compute_content_hash


def test_compute_content_hash_is_stable() -> None:
    digest_a = hashlib.sha256(b"one").hexdigest()
    digest_b = hashlib.sha256(b"two").hexdigest()
    first = compute_content_hash("Subject", "Body", [digest_b, digest_a])
    second = compute_content_hash("Subject", "Body", [digest_a, digest_b])
    assert first == second
