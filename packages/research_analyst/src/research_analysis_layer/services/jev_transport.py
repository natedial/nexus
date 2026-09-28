"""Jev HTTP transport isolation (fakeable for adapter tests)."""

from __future__ import annotations

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
