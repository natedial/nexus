"""LlamaIndex Cloud PDF parsing client."""

import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

logger = structlog.get_logger()


class JobStatus(str, Enum):
    """LlamaIndex parsing job status."""

    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


@dataclass
class ParseResult:
    """Result of PDF parsing."""

    job_id: str
    status: JobStatus
    markdown: str | None = None
    error: str | None = None


class LlamaIndexParser:
    """Client for LlamaIndex Cloud PDF parsing API."""

    BASE_URL = "https://api.cloud.llamaindex.ai/api/v1/parsing"
    POLL_INTERVAL_SECONDS = 5
    MAX_POLL_ATTEMPTS = 60  # 5 minutes max wait

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = httpx.Client(timeout=60.0)
        self._headers = {
            "accept": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        logger.info("Initialized LlamaIndex parser")

    def __del__(self):
        if hasattr(self, "_client"):
            self._client.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def upload(self, file_path: Path) -> str:
        """Upload a PDF file for parsing. Returns job ID."""
        logger.info("Uploading PDF", file_path=str(file_path))

        with open(file_path, "rb") as f:
            files = {"file": (file_path.name, f, "application/pdf")}
            response = self._client.post(
                f"{self.BASE_URL}/upload",
                headers=self._headers,
                files=files,
            )

        response.raise_for_status()
        result = response.json()
        job_id = result["id"]

        logger.info("Upload complete", job_id=job_id)
        return job_id

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def check_status(self, job_id: str) -> JobStatus:
        """Check the status of a parsing job."""
        response = self._client.get(
            f"{self.BASE_URL}/job/{job_id}",
            headers=self._headers,
        )
        response.raise_for_status()
        result = response.json()
        status = JobStatus(result["status"])
        logger.debug("Job status", job_id=job_id, status=status.value)
        return status

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def get_markdown(self, job_id: str) -> str:
        """Retrieve the markdown result of a completed job."""
        response = self._client.get(
            f"{self.BASE_URL}/job/{job_id}/result/markdown",
            headers=self._headers,
        )
        response.raise_for_status()
        result = response.json()
        markdown = result.get("markdown", "")
        logger.info("Retrieved markdown", job_id=job_id, length=len(markdown))
        return markdown

    def wait_for_completion(self, job_id: str) -> JobStatus:
        """Poll until job completes or times out."""
        for attempt in range(self.MAX_POLL_ATTEMPTS):
            status = self.check_status(job_id)

            if status == JobStatus.SUCCESS:
                return status
            elif status == JobStatus.ERROR:
                return status

            # Still pending, wait and retry
            logger.debug(
                "Job still pending",
                job_id=job_id,
                attempt=attempt + 1,
                max_attempts=self.MAX_POLL_ATTEMPTS,
            )
            time.sleep(self.POLL_INTERVAL_SECONDS)

        logger.warning("Job polling timed out", job_id=job_id)
        return JobStatus.PENDING

    def parse(self, file_path: Path) -> ParseResult:
        """Upload, wait for completion, and retrieve markdown."""
        try:
            # Upload the file
            job_id = self.upload(file_path)

            # Wait for processing
            status = self.wait_for_completion(job_id)

            if status == JobStatus.SUCCESS:
                markdown = self.get_markdown(job_id)
                return ParseResult(
                    job_id=job_id,
                    status=status,
                    markdown=markdown,
                )
            elif status == JobStatus.ERROR:
                return ParseResult(
                    job_id=job_id,
                    status=status,
                    error="LlamaIndex parsing failed",
                )
            else:
                return ParseResult(
                    job_id=job_id,
                    status=status,
                    error="Parsing timed out",
                )

        except Exception as e:
            logger.exception("Parse failed", file_path=str(file_path))
            return ParseResult(
                job_id="",
                status=JobStatus.ERROR,
                error=str(e),
            )
