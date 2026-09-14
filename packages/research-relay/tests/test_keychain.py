from __future__ import annotations

from types import SimpleNamespace

import pytest

from research_relay.exceptions import KeychainError
from research_relay import keychain


def test_prefers_security_framework_over_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        keychain,
        "_read_via_security_framework",
        lambda service, account: SimpleNamespace(secret="bridge-secret", status=0),
    )

    def fail_cli(*_args, **_kwargs):
        raise AssertionError("CLI should not run when the Security framework succeeds")

    monkeypatch.setattr(keychain, "_read_via_security_cli", fail_cli)
    assert keychain.get_generic_password("research-relay-proton-smtp", "user@pm.me") == "bridge-secret"


def test_falls_back_to_cli_when_framework_cannot_interact(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        keychain,
        "_read_via_security_framework",
        lambda service, account: SimpleNamespace(secret=None, status=-25308),
    )
    monkeypatch.setattr(
        keychain,
        "_read_via_security_cli",
        lambda service, account, timeout=10: "from-cli",
    )
    assert keychain.get_generic_password("svc", "acct") == "from-cli"


def test_reports_unreadable_when_both_paths_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        keychain,
        "_read_via_security_framework",
        lambda service, account: SimpleNamespace(secret=None, status=-25308),
    )
    monkeypatch.setattr(keychain, "keychain_item_exists", lambda *_args, **_kwargs: True)

    def fake_run(*_args, **_kwargs):
        return SimpleNamespace(returncode=36, stdout="", stderr="")

    monkeypatch.setattr(keychain.subprocess, "run", fake_run)
    with pytest.raises(KeychainError, match="RESEARCH_RELAY_HMAC_KEY"):
        keychain.get_generic_password("research-relay-hmac-key", "hmac")


def test_hmac_env_bypasses_unreadable_keychain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_RELAY_HMAC_KEY", "from-env")
    monkeypatch.setattr(
        keychain,
        "_read_via_security_framework",
        lambda service, account: SimpleNamespace(secret=None, status=-25308),
    )

    def fail_cli(*_args, **_kwargs):
        raise AssertionError("CLI should not run when an env override is set")

    monkeypatch.setattr(keychain, "_read_via_security_cli", fail_cli)
    assert keychain.get_generic_password("research-relay-hmac-key", "hmac") == "from-env"


def test_secrets_file_loads_when_env_empty(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RESEARCH_RELAY_HMAC_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_RELAY_PROTON_PASSWORD", raising=False)
    path = tmp_path / "secrets.env"
    path.write_text("RESEARCH_RELAY_HMAC_KEY=file-hmac\nRESEARCH_RELAY_PROTON_PASSWORD=file-bridge\n")
    path.chmod(0o600)
    keychain.apply_secrets_file(path)
    assert keychain.get_generic_password("research-relay-hmac-key", "hmac") == "file-hmac"
    assert keychain.get_generic_password("research-relay-proton-smtp", "user@pm.me") == "file-bridge"


def test_secrets_file_does_not_override_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_RELAY_HMAC_KEY", "already-set")
    path = tmp_path / "secrets.env"
    path.write_text("RESEARCH_RELAY_HMAC_KEY=from-file\n")
    path.chmod(0o600)
    keychain.apply_secrets_file(path)
    assert keychain.get_generic_password("research-relay-hmac-key", "hmac") == "already-set"


def test_secrets_file_rejects_open_mode(tmp_path) -> None:
    path = tmp_path / "secrets.env"
    path.write_text("RESEARCH_RELAY_HMAC_KEY=x\n")
    path.chmod(0o644)
    with pytest.raises(KeychainError, match="chmod 600"):
        keychain.apply_secrets_file(path)
