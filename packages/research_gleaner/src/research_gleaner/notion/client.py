from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

NOTION_BASE_URL = "https://api.notion.com/v1"
DEFAULT_NOTION_VERSION = "2026-03-11"


class NotionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class NotionClient:
    def __init__(
        self,
        token: str,
        *,
        api_version: str = DEFAULT_NOTION_VERSION,
        timeout_seconds: float = 60.0,
        min_interval: float = 0.34,
        retries: int = 4,
    ):
        if not token.strip():
            raise ValueError("Notion token must not be empty")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": api_version,
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(timeout=timeout_seconds, headers=self._headers)
        self._min_interval = min_interval
        self._retries = retries
        self._last_request = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> NotionClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(self._retries + 1):
            elapsed = time.monotonic() - self._last_request
            if elapsed < self._min_interval:
                time.sleep(self._min_interval - elapsed)
            response = self._client.request(
                method,
                f"{NOTION_BASE_URL}{path}",
                json=json_body,
                params=params,
            )
            self._last_request = time.monotonic()
            if response.status_code == 429 and attempt < self._retries:
                delay = float(response.headers.get("Retry-After", "1"))
                time.sleep(max(delay, 0.0))
                continue
            if response.status_code in {500, 502, 503, 504, 529} and attempt < self._retries:
                time.sleep(min(2**attempt, 8))
                continue
            if response.status_code >= 400:
                raise NotionError(
                    f"Notion API {response.status_code}: {response.text[:500]}",
                    status_code=response.status_code,
                )
            if response.status_code == 204:
                return {}
            return response.json()
        raise AssertionError("unreachable")

    def query_data_source(
        self,
        data_source_id: str,
        *,
        filter_body: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"page_size": page_size}
        if filter_body:
            body["filter"] = filter_body
        if sorts:
            body["sorts"] = sorts
        if start_cursor:
            body["start_cursor"] = start_cursor
        return self._request(
            "POST",
            f"/data_sources/{data_source_id}/query",
            json_body=body,
        )

    def list_block_children(
        self,
        block_id: str,
        *,
        start_cursor: str | None = None,
        page_size: int = 100,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": page_size}
        if start_cursor:
            params["start_cursor"] = start_cursor
        return self._request("GET", f"/blocks/{block_id}/children", params=params)

    def paginate(
        self,
        fetch_page: Callable[..., dict[str, Any]],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            payload = fetch_page(start_cursor=cursor)
            results.extend(payload.get("results", []))
            cursor = payload.get("next_cursor")
            if not payload.get("has_more") or not cursor:
                return results
