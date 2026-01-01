"""Google Drive folder watcher using service account authentication."""

import tempfile
from dataclasses import dataclass
from pathlib import Path

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

logger = structlog.get_logger()


@dataclass
class DriveFile:
    """Represents a file from Google Drive."""

    id: str
    name: str
    mime_type: str


class DriveWatcher:
    """Watches a Google Drive folder for new PDF files."""

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
    PDF_MIME_TYPE = "application/pdf"

    def __init__(self, credentials_path: Path, folder_id: str):
        self.folder_id = folder_id
        self._credentials = service_account.Credentials.from_service_account_file(
            str(credentials_path),
            scopes=self.SCOPES,
        )
        self._service = build("drive", "v3", credentials=self._credentials)
        logger.info("Initialized Drive watcher", folder_id=folder_id)

    def list_pdfs(self) -> list[DriveFile]:
        """List all PDF files in the watched folder."""
        query = f"'{self.folder_id}' in parents and mimeType = '{self.PDF_MIME_TYPE}' and trashed = false"

        results = (
            self._service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name, mimeType)",
                orderBy="createdTime desc",
            )
            .execute()
        )

        files = results.get("files", [])
        logger.debug("Found PDFs in folder", count=len(files))

        return [
            DriveFile(
                id=f["id"],
                name=f["name"],
                mime_type=f["mimeType"],
            )
            for f in files
        ]

    def download_file(self, file_id: str, file_name: str) -> Path:
        """Download a file to a temporary location."""
        request = self._service.files().get_media(fileId=file_id)

        # Create temp file with original extension
        suffix = Path(file_name).suffix or ".pdf"
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)

        with open(temp_file.name, "wb") as f:
            downloader = MediaIoBaseDownload(f, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    logger.debug(
                        "Download progress",
                        file_name=file_name,
                        progress=f"{int(status.progress() * 100)}%",
                    )

        logger.info("Downloaded file", file_name=file_name, path=temp_file.name)
        return Path(temp_file.name)

    def get_new_files(self, processed_ids: set[str]) -> list[DriveFile]:
        """Get files that haven't been processed yet."""
        all_files = self.list_pdfs()
        new_files = [f for f in all_files if f.id not in processed_ids]
        logger.info("Found new files", total=len(all_files), new=len(new_files))
        return new_files
