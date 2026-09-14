class RelayError(Exception):
    """Base error for the research relay."""


class ConfigError(RelayError):
    """Invalid configuration."""


class KeychainError(RelayError):
    """A required macOS Keychain item is missing or unreadable."""


class TemporaryRelayError(RelayError):
    """Retryable IMAP/SMTP/network failure."""


class PermanentRelayError(RelayError):
    """Failure that should not be retried indefinitely."""


class AlreadyRunningError(RelayError):
    """Another relay process holds the lock."""


class DriveAuthError(RelayError):
    """Google Drive rejected the OAuth token or Drive scope."""
