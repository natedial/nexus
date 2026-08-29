import json
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from research_relay.drive_archive import upload_html, upload_pdf, upload_pdf_as_gdoc
from research_relay.exceptions import DriveAuthError, TemporaryRelayError


class _Resp:
    def __init__(self, payload: dict, status: int = 200):
        self.status = status
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def test_upload_pdf_posts_multipart_to_folder() -> None:
    captured = {}

    def fake_urlopen(request, timeout=0, context=None):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items()) if hasattr(request, "header_items") else request.headers
        captured["body"] = request.data
        return _Resp({"id": "file1", "name": "a.pdf"})

    with patch("research_relay.drive_archive.urlopen", fake_urlopen):
        file_id = upload_pdf(
            access_token="tok",
            folder_id="pdfFolder",
            name="2026-08-28_subj_a.pdf",
            payload=b"%PDF-1.4",
        )
    assert file_id == "file1"
    assert "upload/drive/v3/files" in captured["url"]
    assert "uploadType=multipart" in captured["url"]
    body = captured["body"]
    assert b"pdfFolder" in body
    assert b"2026-08-28_subj_a.pdf" in body
    assert b"application/pdf" in body
    headers = {str(k).lower(): v for k, v in captured["headers"].items()}
    auth = headers.get("authorization") or headers.get("Authorization")
    assert auth == "Bearer tok" or any("Bearer tok" in str(v) for v in captured["headers"].values())


def test_upload_gdoc_uses_google_document_mime() -> None:
    captured = {}

    def fake_urlopen(request, timeout=0, context=None):
        captured["body"] = request.data
        return _Resp({"id": "doc1"})

    with patch("research_relay.drive_archive.urlopen", fake_urlopen):
        file_id = upload_pdf_as_gdoc(
            access_token="tok",
            folder_id="docsFolder",
            name="2026-08-28_subj_a",
            payload=b"%PDF-1.4",
        )
    assert file_id == "doc1"
    assert b"application/vnd.google-apps.document" in captured["body"]
    assert b'"convert"' not in captured["body"]


def test_upload_html() -> None:
    def fake_urlopen(request, timeout=0, context=None):
        return _Resp({"id": "html1"})

    with patch("research_relay.drive_archive.urlopen", fake_urlopen):
        assert upload_html("tok", "pdfFolder", "a.html", "<html></html>") == "html1"


def test_drive_500_is_temporary() -> None:
    def fake_urlopen(request, timeout=0, context=None):
        raise HTTPError(request.full_url, 500, "err", hdrs=None, fp=BytesIO(b"{}"))

    with patch("research_relay.drive_archive.urlopen", fake_urlopen):
        with pytest.raises(TemporaryRelayError):
            upload_pdf("tok", "f", "a.pdf", b"x")


def test_drive_401_is_auth_error() -> None:
    def fake_urlopen(request, timeout=0, context=None):
        raise HTTPError(request.full_url, 401, "denied", hdrs=None, fp=BytesIO(b"{}"))

    with patch("research_relay.drive_archive.urlopen", fake_urlopen):
        with pytest.raises(DriveAuthError):
            upload_pdf("tok", "f", "a.pdf", b"x")
