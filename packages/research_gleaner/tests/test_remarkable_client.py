import sys
import types

import pytest

from research_gleaner.remarkable.client import RemarkableLibrary

SECRET_PREFIX = "devicetoken: eyJhbGc"


def _install_get_rmapi(monkeypatch, get_rmapi):
    module = types.ModuleType("remarkable_mcp.api")
    module.get_rmapi = get_rmapi
    monkeypatch.setitem(sys.modules, "remarkable_mcp.api", module)


def test_invalid_token_error_does_not_leak_token_text(monkeypatch):
    def get_rmapi():
        raise ValueError(
            "Invalid token format. Expected JSON or JWT token.\n"
            f"Token starts with: {SECRET_PREFIX}..."
        )

    _install_get_rmapi(monkeypatch, get_rmapi)

    with pytest.raises(ValueError) as excinfo:
        RemarkableLibrary()

    assert SECRET_PREFIX not in str(excinfo.value)
    assert "REMARKABLE_TOKEN" in str(excinfo.value)
    # The original exception (which carries the prefix) must not be chained.
    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__


def test_other_value_errors_are_not_rewritten(monkeypatch):
    def get_rmapi():
        raise ValueError("something else")

    _install_get_rmapi(monkeypatch, get_rmapi)

    with pytest.raises(ValueError, match="something else"):
        RemarkableLibrary()
