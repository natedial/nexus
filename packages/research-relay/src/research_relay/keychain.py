from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import ctypes
import ctypes.util
import os
import subprocess
import sys

from research_relay.exceptions import KeychainError

_ERR_ITEM_NOT_FOUND = -25300
_ERR_INTERACTION_NOT_ALLOWED = -25308
_ALLOWED_SECRET_KEYS = frozenset(
    {
        "RESEARCH_RELAY_HMAC_KEY",
        "RESEARCH_RELAY_PROTON_PASSWORD",
    }
)


def secrets_path_for_config(config_path: Path) -> Path:
    env = os.environ.get("RESEARCH_RELAY_SECRETS_FILE", "").strip()
    if env:
        return Path(env).expanduser()
    return Path(config_path).expanduser().parent / "secrets.env"


def apply_secrets_file(path: str | Path) -> Path | None:
    """Load HMAC/Bridge secrets from a mode-600 file into os.environ.

    Existing environment variables win. Used so LaunchAgent can run without
    Keychain access on macOS 26. Never put this file in the LaunchAgent plist.
    """
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        return None
    mode = file_path.stat().st_mode & 0o777
    if mode & 0o077:
        raise KeychainError(
            f"secrets file {file_path} must not be group/world-readable (mode {oct(mode)}); chmod 600"
        )
    text = file_path.read_text(encoding="utf-8")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key not in _ALLOWED_SECRET_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if value and not os.environ.get(key, "").strip():
            os.environ[key] = value
    return file_path


def _env_var_for(service: str, account: str) -> str | None:
    if account == "hmac" or service.endswith("hmac-key"):
        return "RESEARCH_RELAY_HMAC_KEY"
    if "proton-smtp" in service:
        return "RESEARCH_RELAY_PROTON_PASSWORD"
    return None


def _env_secret(service: str, account: str) -> str | None:
    name = _env_var_for(service, account)
    if not name:
        return None
    value = os.environ.get(name, "").strip()
    return value or None


def get_generic_password(service: str, account: str, *, timeout: float = 10) -> str:
    override = _env_secret(service, account)
    if override:
        return override
    framework = _read_via_security_framework(service, account)
    if framework.status == 0:
        secret = (framework.secret or "").rstrip("\n")
        if not secret:
            raise KeychainError(f"Keychain item for service {service!r} is empty")
        return secret
    try:
        return _read_via_security_cli(service, account, timeout=timeout)
    except KeychainError:
        if framework.status == _ERR_INTERACTION_NOT_ALLOWED:
            hint = _env_var_for(service, account)
            extra = (
                f" Set {hint} in the environment for this process (not in config.toml)."
                if hint
                else ""
            )
            raise KeychainError(
                f"Keychain item exists for service {service!r} account {account!r} "
                f"but macOS denied access (Security.framework {framework.status}). "
                f"On macOS 26 this Python cannot read Keychain.{extra}"
            ) from None
        raise


@dataclass(frozen=True)
class _FrameworkResult:
    secret: str | None
    status: int | None


def keychain_item_exists(service: str, account: str, *, timeout: float = 10) -> bool:
    result = subprocess.run(
        ["security", "find-generic-password", "-s", service, "-a", account],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return result.returncode == 0


def _read_via_security_framework(service: str, account: str) -> _FrameworkResult:
    if sys.platform != "darwin":
        return _FrameworkResult(None, None)
    lib_name = ctypes.util.find_library("Security")
    if not lib_name:
        return _FrameworkResult(None, None)
    try:
        sec = ctypes.CDLL(lib_name)
        sec.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_void_p,
        ]
        sec.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        sec.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        sec.SecKeychainItemFreeContent.restype = ctypes.c_int32
        if hasattr(sec, "SecKeychainSetUserInteractionAllowed"):
            sec.SecKeychainSetUserInteractionAllowed.argtypes = [ctypes.c_ubyte]
            sec.SecKeychainSetUserInteractionAllowed.restype = ctypes.c_int32
            sec.SecKeychainSetUserInteractionAllowed(1)

        service_b = service.encode("utf-8")
        account_b = account.encode("utf-8")
        length = ctypes.c_uint32(0)
        data = ctypes.c_void_p()
        status = int(
            sec.SecKeychainFindGenericPassword(
                None,
                len(service_b),
                service_b,
                len(account_b),
                account_b,
                ctypes.byref(length),
                ctypes.byref(data),
                None,
            )
        )
        if status != 0:
            return _FrameworkResult(None, status)
        try:
            if not data.value or length.value == 0:
                return _FrameworkResult("", 0)
            secret = ctypes.string_at(data.value, length.value).decode("utf-8")
            return _FrameworkResult(secret, 0)
        finally:
            if data.value:
                sec.SecKeychainItemFreeContent(None, data)
    except (OSError, AttributeError, UnicodeDecodeError, ValueError):
        return _FrameworkResult(None, None)


def _read_via_security_cli(service: str, account: str, *, timeout: float = 10) -> str:
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-s",
            service,
            "-a",
            account,
            "-w",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        if keychain_item_exists(service, account, timeout=timeout):
            raise KeychainError(
                f"Keychain item exists for service {service!r} account {account!r} "
                f"but the password could not be read (security exit {result.returncode})"
            )
        raise KeychainError(
            f"Keychain item not found for service {service!r} account {account!r}"
        )
    secret = result.stdout.rstrip("\n")
    if not secret:
        raise KeychainError(f"Keychain item for service {service!r} is empty")
    return secret
