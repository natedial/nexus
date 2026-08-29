import pytest

from research_relay.domain import (
    address_is_one_of,
    domain_allowed,
    extract_sender_mailbox,
    message_id_from_domain,
)


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("Alice Example <alice@candidates.edu>", "alice@candidates.edu"),
        ("alice@candidates.edu", "alice@candidates.edu"),
        ("Alice <Alice@Candidates.EDU>", "alice@candidates.edu"),
        ('"Example, Alice" <alice@candidates.edu>', "alice@candidates.edu"),
    ],
)
def test_extract_sender_mailbox_normalizes_address(address: str, expected: str) -> None:
    mailbox = extract_sender_mailbox(address)
    assert mailbox.address == expected
    assert mailbox.domain == "candidates.edu"


def test_extract_sender_mailbox_rejects_missing_address() -> None:
    with pytest.raises(ValueError):
        extract_sender_mailbox("Alice Example")


def test_exact_domain_match_allows_configured_domain() -> None:
    assert domain_allowed("alice@candidates.edu", ["candidates.edu"], allow_subdomains=False)


def test_exact_domain_match_is_case_insensitive() -> None:
    assert domain_allowed("alice@CANDIDATES.EDU", ["Candidates.Edu"], allow_subdomains=False)


def test_exact_domain_match_rejects_subdomain_when_disabled() -> None:
    assert not domain_allowed(
        "alice@mail.candidates.edu", ["candidates.edu"], allow_subdomains=False
    )


def test_subdomain_match_allows_true_subdomains() -> None:
    assert domain_allowed(
        "alice@mail.dept.candidates.edu", ["candidates.edu"], allow_subdomains=True
    )


def test_subdomain_match_still_allows_exact_apex() -> None:
    assert domain_allowed("alice@candidates.edu", ["candidates.edu"], allow_subdomains=True)


def test_rejects_spoof_suffix_domain() -> None:
    assert not domain_allowed(
        "alice@candidates.edu.attacker.example",
        ["candidates.edu"],
        allow_subdomains=True,
    )


def test_rejects_prefix_lookalike_domain() -> None:
    assert not domain_allowed(
        "alice@notcandidates.edu", ["candidates.edu"], allow_subdomains=True
    )


def test_rejects_embedded_lookalike() -> None:
    assert not domain_allowed(
        "alice@evil-candidates.edu.example", ["candidates.edu"], allow_subdomains=True
    )


def test_does_not_trust_substring_in_local_part() -> None:
    assert not domain_allowed(
        "alice@candidates.edu@evil.example", ["candidates.edu"], allow_subdomains=True
    )


def test_does_not_match_partial_suffix_without_dot_boundary() -> None:
    assert not domain_allowed(
        "alice@mycandidates.edu", ["candidates.edu"], allow_subdomains=True
    )


def test_address_is_one_of_matches_relay_from() -> None:
    assert address_is_one_of(
        "Research Dist <rsrch_dist@protonmail.ch>",
        ["rsrch_dist@protonmail.ch", "rsrch_dist@protonmail.ch"],
    )
    assert not address_is_one_of("usrateswatch@pm.me", ["rsrch_dist@protonmail.ch"])


def test_message_id_from_domain_detects_relay_ids() -> None:
    assert message_id_from_domain("<deadbeefcafebabe@relay.local>", "relay.local")
    assert not message_id_from_domain("<native@pm.me>", "relay.local")
    assert not message_id_from_domain("", "relay.local")
