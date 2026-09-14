from __future__ import annotations

import json
import ssl
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from research_relay.exceptions import DriveAuthError, TemporaryRelayError

_UPLOAD = "https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart"
_FILES = "https://www.googleapis.com/drive/v3/files"


def upload_pdf(access_token: str, folder_id: str, name: str, payload: bytes) -> str:
    return _upload(
        access_token=access_token,
        folder_id=folder_id,
        name=name,
        payload=payload,
        metadata_mime="application/pdf",
        media_mime="application/pdf",
    )


def upload_pdf_as_gdoc(access_token: str, folder_id: str, name: str, payload: bytes) -> str:
    return _upload(
        access_token=access_token,
        folder_id=folder_id,
        name=name,
        payload=payload,
        metadata_mime="application/vnd.google-apps.document",
        media_mime="application/pdf",
    )


def upload_html(access_token: str, folder_id: str, name: str, html: str) -> str:
    return _upload(
        access_token=access_token,
        folder_id=folder_id,
        name=name,
        payload=html.encode("utf-8"),
        metadata_mime="text/html",
        media_mime="text/html",
    )


def get_file_metadata(*, access_token: str, file_id: str) -> dict:
    url = f"{_FILES}/{file_id}?fields=id,name,mimeType"
    request = Request(
        url,
        method="GET",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    return _json_request(request)


def _upload(
    *,
    access_token: str,
    folder_id: str,
    name: str,
    payload: bytes,
    metadata_mime: str,
    media_mime: str,
) -> str:
    boundary = f"relay_{uuid.uuid4().hex}"
    meta = json.dumps(
        {
            "name": name,
            "mimeType": metadata_mime,
            "parents": [folder_id],
        }
    ).encode("utf-8")
    body = (
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n".encode("utf-8")
        + meta
        + f"\r\n--{boundary}\r\nContent-Type: {media_mime}\r\n\r\n".encode("utf-8")
        + payload
        + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )
    request = Request(
        _UPLOAD,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": f"multipart/related; boundary={boundary}",
        },
    )
    data = _json_request(request)
    file_id = str(data.get("id") or "")
    if not file_id:
        raise TemporaryRelayError("Drive upload response missing file id")
    return file_id


def _json_request(request: Request) -> dict:
    context = ssl.create_default_context()
    try:
        with urlopen(request, timeout=60, context=context) as response:
            raw = response.read()
    except HTTPError as exc:
        if exc.code in {401, 403}:
            raise DriveAuthError(f"Drive HTTP {exc.code}") from exc
        raise TemporaryRelayError(f"Drive HTTP {exc.code}") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise TemporaryRelayError(f"Drive request failed: {exc.__class__.__name__}") from exc
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise TemporaryRelayError("Drive response was not JSON") from exc
    if not isinstance(payload, dict):
        raise TemporaryRelayError("Drive response was not an object")
    return payload
