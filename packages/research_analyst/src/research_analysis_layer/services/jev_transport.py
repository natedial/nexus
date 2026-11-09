"""Jev HTTP transport isolation (fakeable for adapter tests)."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

DEFAULT_JEV_BASE_URL = "https://api.typesafe.ai"
DEFAULT_JEV_ENDPOINT_PATH = "/v1/systemone"


class JevTransportError(Exception):
    """Transport-level failure talking to TypeSafe System One."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        payload: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.payload = payload


@dataclass(slots=True)
class JevTransportResponse:
    """Raw HTTP response payload from System One."""

    status_code: int
    body: dict[str, Any]
    headers: dict[str, str]


class JevTransport(Protocol):
    """Sync POST transport; adapters depend on this, not httpx directly."""

    def post_systemone(self, request_body: dict[str, Any]) -> JevTransportResponse:
        """POST a System One evaluation request and return JSON."""


class JevBudgetExhausted(JevTransportError):
    """A frozen request or token cap would be exceeded; never retryable."""

    def __init__(self, message: str) -> None:
        super().__init__(message, retryable=False)


class CappedJevTransport:
    """Hard request/token ceiling around any ``JevTransport``.

    Counts every attempt the adapter makes, retries included, because each one
    is a billable HTTP call. Tokens are checked before a call against a
    deliberately pessimistic size estimate and reconciled afterwards from
    reported usage. A response without usable usage is charged at the
    estimate, so unknown spend counts against the cap instead of being ignored.
    """

    # Pessimistic: real tokenizers average well above 3 characters per token.
    _CHARS_PER_TOKEN = 3.0
    # Allowance for the completion when the request carries no output cap.
    _OUTPUT_ALLOWANCE_TOKENS = 512

    def __init__(
        self,
        inner: JevTransport,
        *,
        max_requests: int,
        max_total_tokens: int,
    ) -> None:
        if max_requests <= 0:
            raise ValueError("max_requests must be positive")
        if max_total_tokens <= 0:
            raise ValueError("max_total_tokens must be positive")
        self._inner = inner
        self.max_requests = max_requests
        self.max_total_tokens = max_total_tokens
        self._lock = threading.Lock()
        self.requests_made = 0
        self.tokens_used = 0.0

    def post_systemone(self, request_body: dict[str, Any]) -> JevTransportResponse:
        estimate = self._estimate_tokens(request_body)
        with self._lock:
            if self.requests_made >= self.max_requests:
                raise JevBudgetExhausted(
                    f"Jev request cap reached ({self.max_requests})"
                )
            if self.tokens_used + estimate > self.max_total_tokens:
                raise JevBudgetExhausted(
                    "Jev token cap would be exceeded "
                    f"(used {self.tokens_used:.0f} + est {estimate:.0f} "
                    f"> {self.max_total_tokens})"
                )
            # Reserve before the call so a failed attempt still counts.
            self.requests_made += 1
            self.tokens_used += estimate
        response = self._inner.post_systemone(request_body)
        actual = self._reported_tokens(response.body)
        if actual is not None:
            with self._lock:
                self.tokens_used += actual - estimate
        return response

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "requests_made": self.requests_made,
                "max_requests": self.max_requests,
                "tokens_used": self.tokens_used,
                "max_total_tokens": self.max_total_tokens,
            }

    @classmethod
    def _estimate_tokens(cls, request_body: dict[str, Any]) -> float:
        try:
            size = len(json.dumps(request_body, default=str))
        except (TypeError, ValueError):
            size = len(str(request_body))
        return size / cls._CHARS_PER_TOKEN + cls._OUTPUT_ALLOWANCE_TOKENS

    @staticmethod
    def _reported_tokens(body: dict[str, Any]) -> float | None:
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return None

        def num(key: str) -> float | None:
            value = usage.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
            return None

        total = num("total_tokens")
        if total is not None:
            return total
        parts = [num("input_tokens"), num("output_tokens")]
        if all(part is not None for part in parts):
            return float(sum(parts))  # type: ignore[arg-type]
        return None


class HttpJevTransport:
    """Live httpx transport for TypeSafe System One."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_JEV_BASE_URL,
        timeout_seconds: float = 30.0,
        endpoint_path: str = DEFAULT_JEV_ENDPOINT_PATH,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Jev API key must not be empty")
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._endpoint_path = endpoint_path

    def post_systemone(self, request_body: dict[str, Any]) -> JevTransportResponse:
        url = f"{self._base_url}{self._endpoint_path}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, json=request_body, headers=headers)
        except httpx.TimeoutException as exc:
            raise JevTransportError(
                f"Jev request timed out after {self._timeout}s",
                retryable=True,
            ) from exc
        except httpx.TransportError as exc:
            raise JevTransportError(
                f"Jev transport error: {exc}",
                retryable=True,
            ) from exc

        try:
            body = response.json()
        except ValueError:
            body = {"raw_text": response.text}

        if response.status_code >= 400:
            retryable = response.status_code in {408, 429, 500, 502, 503, 504, 529}
            message = f"Jev HTTP {response.status_code}"
            if isinstance(body, dict):
                detail = body.get("detail") or body.get("error") or body.get("message")
                if detail:
                    message = f"{message}: {detail}"
            raise JevTransportError(
                message,
                status_code=response.status_code,
                retryable=retryable,
                payload=body,
            )

        if not isinstance(body, dict):
            raise JevTransportError(
                "Jev response JSON must be an object",
                status_code=response.status_code,
                retryable=False,
                payload=body,
            )
        return JevTransportResponse(
            status_code=response.status_code,
            body=body,
            headers={k: v for k, v in response.headers.items()},
        )


class FakeJevTransport:
    """Scriptable transport for adapter unit tests (no network)."""

    def __init__(
        self,
        *,
        response_body: dict[str, Any] | None = None,
        responder: Any = None,
        error: JevTransportError | None = None,
        errors: list[JevTransportError] | None = None,
    ) -> None:
        self._response_body = response_body
        self._responder = responder
        self._errors = list(errors or [])
        if error is not None:
            self._errors.insert(0, error)
        self.requests: list[dict[str, Any]] = []

    def post_systemone(self, request_body: dict[str, Any]) -> JevTransportResponse:
        self.requests.append(request_body)
        if self._errors:
            raise self._errors.pop(0)
        if self._responder is not None:
            body = self._responder(request_body)
        elif self._response_body is not None:
            body = self._response_body
        else:
            body = {"model": "jev-1.13.0", "answers": {}, "usage": {}}
        if not isinstance(body, dict):
            raise JevTransportError("fake responder returned non-object", retryable=False)
        return JevTransportResponse(status_code=200, body=body, headers={})
