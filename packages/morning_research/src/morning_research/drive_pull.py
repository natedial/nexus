"""Google Drive pull: list, download, and hash candidate PDFs for a run.

Patterned after `research_parser.src.drive.watcher.DriveWatcher`, but returns
richer per-file metadata (content hash, revision id, size) and performs the
download + de-duplication against persisted state itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from morning_research.models import CandidateDoc, RunState
from morning_research.state import already_processed, is_duplicate_content

logger = structlog.get_logger()

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
PDF_MIME_TYPE = "application/pdf"
DRIVE_FIELDS = (
    "nextPageToken, files(id, name, mimeType, modifiedTime, createdTime, "
    "size, md5Checksum, headRevisionId)"
)


@dataclass
class DrivePullResult:
    candidates: list[CandidateDoc]
    """All non-duplicate, in-window PDFs, downloaded to work_dir/docs/."""
    skipped_duplicates: list[dict[str, str]]
    """file_id/name/reason for files skipped as already-processed duplicates."""
    total_listed: int


class DrivePuller:
    """Lists and downloads PDFs from the watched Drive folder for a run window."""

    def __init__(self, credentials_path: Path, folder_id: str) -> None:
        self.folder_id = folder_id
        credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path), scopes=SCOPES
        )
        self._service = build("drive", "v3", credentials=credentials)
        logger.info("Initialized Drive puller", folder_id=folder_id)

    def _list_all_pdfs(self) -> list[dict]:
        query = (
            f"'{self.folder_id}' in parents and mimeType = '{PDF_MIME_TYPE}' "
            "and trashed = false"
        )
        files: list[dict] = []
        page_token = None
        while True:
            response = (
                self._service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields=DRIVE_FIELDS,
                    orderBy="modifiedTime desc",
                    pageSize=100,
                    pageToken=page_token,
                )
                .execute()
            )
            files.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        logger.debug("Listed PDFs in folder", count=len(files))
        return files

    @staticmethod
    def _parse_drive_timestamp(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))

    def _in_window(self, file_meta: dict, window_start: datetime) -> bool:
        modified = self._parse_drive_timestamp(file_meta["modifiedTime"])
        created = self._parse_drive_timestamp(file_meta.get("createdTime", file_meta["modifiedTime"]))
        return modified >= window_start or created >= window_start

    def _download(self, file_id: str, dest_path: Path) -> bytes:
        request = self._service.files().get_media(fileId=file_id)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug(
                        "Download progress",
                        file_id=file_id,
                        progress=f"{int(status.progress() * 100)}%",
                    )
        return dest_path.read_bytes()

    def pull(
        self,
        *,
        window_start: datetime,
        work_dir: Path,
        state: RunState,
    ) -> DrivePullResult:
        """List, filter, download, and hash candidate PDFs for this run.

        Writes `work_dir/manifest.json` describing every candidate that was
        downloaded (post de-duplication).
        """
        docs_dir = work_dir / "docs"
        all_files = self._list_all_pdfs()

        in_window = [f for f in all_files if self._in_window(f, window_start)]
        logger.info(
            "Filtered PDFs by window",
            total=len(all_files),
            in_window=len(in_window),
            window_start=window_start.isoformat(),
        )

        candidates: list[CandidateDoc] = []
        skipped_duplicates: list[dict[str, str]] = []

        for file_meta in in_window:
            file_id = file_meta["id"]
            name = file_meta["name"]
            size_bytes = int(file_meta.get("size", 0) or 0)

            dest_path = docs_dir / f"{file_id}.pdf"
            content_bytes = self._download(file_id, dest_path)
            sha256_hash = hashlib.sha256(content_bytes).hexdigest()
            content_hash = f"sha256:{sha256_hash}"

            if already_processed(state, file_id, content_hash):
                skipped_duplicates.append(
                    {"file_id": file_id, "name": name, "reason": "same_file_same_content"}
                )
                dest_path.unlink(missing_ok=True)
                continue

            if is_duplicate_content(state, content_hash):
                skipped_duplicates.append(
                    {"file_id": file_id, "name": name, "reason": "content_hash_seen_elsewhere"}
                )
                dest_path.unlink(missing_ok=True)
                continue

            candidates.append(
                CandidateDoc(
                    file_id=file_id,
                    name=name,
                    mime_type=file_meta.get("mimeType", PDF_MIME_TYPE),
                    modified_time=self._parse_drive_timestamp(file_meta["modifiedTime"]),
                    created_time=self._parse_drive_timestamp(
                        file_meta.get("createdTime", file_meta["modifiedTime"])
                    ),
                    size_bytes=size_bytes or len(content_bytes),
                    content_hash=content_hash,
                    local_path=dest_path,
                    head_revision_id=file_meta.get("headRevisionId"),
                    md5_checksum=file_meta.get("md5Checksum"),
                )
            )

        _write_manifest(work_dir, candidates, skipped_duplicates)

        return DrivePullResult(
            candidates=candidates,
            skipped_duplicates=skipped_duplicates,
            total_listed=len(all_files),
        )


def _write_manifest(
    work_dir: Path,
    candidates: list[CandidateDoc],
    skipped_duplicates: list[dict[str, str]],
) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "candidates": [c.to_manifest_dict() for c in candidates],
        "skipped_duplicates": skipped_duplicates,
    }
    (work_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
