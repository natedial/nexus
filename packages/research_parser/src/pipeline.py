"""Parse-and-store orchestrator for research PDFs."""

import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import structlog


def _add_shared_workspace_paths() -> None:
    module_path = Path(__file__).resolve()
    repo_root = module_path.parents[1]

    candidates: list[Path] = []
    env_root = os.getenv("RESEARCH_PROCESSING_ROOT")
    if env_root:
        candidates.append(Path(env_root))
    candidates.extend([repo_root.parent, repo_root])

    for candidate in candidates:
        if not candidate.exists():
            continue
        if not (candidate / "research_pipeline_ops").exists():
            continue
        candidate_str = str(candidate)
        if candidate_str not in sys.path:
            sys.path.insert(0, candidate_str)


_add_shared_workspace_paths()

try:
    from research_pipeline_ops import PipelineOpsClient, make_document_key
except ImportError:
    PipelineOpsClient = None  # type: ignore[misc, assignment]

    def make_document_key(*, file_id: str, **_kwargs) -> str:
        return file_id

from src.config import Settings
from src.drive import DriveWatcher
from src.intake.relay_adapter import RelayIntakeAdapter
from src.intake.relay_contract import RelayIntakeArtifact
from src.parser import (
    DoclingBackend,
    MinerUBackend,
    blocks_to_markdown,
    filter_blocks_present_in_text,
    load_blocks,
    parse_with_optional_ocr,
    strip_boilerplate,
    write_artifacts,
)
from src.research_memory import ResearchArtifactContext
from src.source import SourceDocument
from src.storage import PostgresSourceStore, StateStore
from src.storage.state import ProcessingStatus

logger = structlog.get_logger()

_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
_SOURCE_DISPLAY = {
    "BARCLAYS": "Barclays",
    "CITI": "Citi",
    "DB": "Deutsche Bank",
    "GS": "Goldman Sachs",
    "JPM": "J.P. Morgan",
    "MS": "Morgan Stanley",
}
_CLEAN_TEXT_ARTIFACT = "clean_text.md"
_PARSE_ARTIFACT = "parse.json"
_BLOCKS_ARTIFACT = "blocks.jsonl"
_FIGURES_ARTIFACT = "figures.jsonl"


class _NoopPipelineOpsClient:
    def flush(self) -> None:
        return None

    def start_run(self, **kwargs) -> str | None:
        return None

    def update_run(self, *args, **kwargs) -> None:
        return None

    def emit_stage_event(self, **kwargs) -> None:
        return None

    @contextmanager
    def track_stage(self, **kwargs):
        yield None


def _parse_date_from_filename(file_name: str) -> str | None:
    match = _DATE_PREFIX_RE.match(file_name)
    if not match:
        return None
    try:
        datetime.strptime(match.group(1), "%Y-%m-%d")
        return match.group(1)
    except ValueError:
        return None


def _source_from_filename(file_name: str) -> str | None:
    parts = file_name.split("_", 2)
    if len(parts) < 2:
        return None
    return _SOURCE_DISPLAY.get(parts[1].upper())


def _plain_text_from_html(html: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", without_tags).strip()


def build_source_document(file_id: str, file_name: str, full_text: str) -> SourceDocument:
    return SourceDocument(
        document_id=file_id,
        document_name=file_name,
        full_text=full_text,
        source=_source_from_filename(file_name),
        source_date=_parse_date_from_filename(file_name),
        document_uri=f"gdrive://{file_id}",
        document_link=f"https://drive.google.com/file/d/{file_id}/view",
    )


def build_source_document_from_relay(
    artifact: RelayIntakeArtifact,
    file_name: str,
    full_text: str,
) -> SourceDocument:
    if artifact.archive_html_drive_id:
        document_link = (
            f"https://drive.google.com/file/d/{artifact.archive_html_drive_id}/view"
        )
    else:
        drive_ids = list(artifact.archive_pdf_drive_ids.values())
        document_link = (
            f"https://drive.google.com/file/d/{drive_ids[0]}/view" if drive_ids else None
        )
    return SourceDocument(
        document_id=artifact.document_id(),
        document_name=file_name,
        full_text=full_text,
        source=artifact.sender_address or "relay",
        source_date=artifact.source_date(),
        document_uri=f"relay://{artifact.relay_key}",
        document_link=document_link,
    )


class Pipeline:
    """Download, parse, and store source-grounded research PDFs."""

    ops = _NoopPipelineOpsClient()
    _active_run_key: str | None = None

    def __init__(self, settings: Settings):
        self.settings = settings
        self.drive = DriveWatcher(
            credentials_path=settings.google_credentials_path,
            folder_id=settings.google_drive_folder_id,
        )
        self.docling_backend = DoclingBackend(do_ocr=False)
        self.docling_ocr_backend = None
        try:
            self.docling_backend._get_converter()
            logger.info("Docling available", backend="docling")
        except Exception as exc:
            logger.warning(
                "Docling unavailable; will fall back to local MinerU if enabled",
                backend="docling",
                error=str(exc),
            )
        self.mineru_backend = None
        if settings.mineru_enabled:
            if settings.mineru_bin_path is None:
                logger.warning("MinerU enabled but binary path not set; skipping")
            elif not settings.mineru_bin_path.exists():
                logger.warning(
                    "MinerU enabled but binary path does not exist; skipping",
                    binary_path=str(settings.mineru_bin_path),
                )
            else:
                try:
                    self.mineru_backend = MinerUBackend(
                        binary_path=settings.mineru_bin_path,
                        cli_backend=settings.mineru_backend,
                        timeout_seconds=settings.mineru_timeout_seconds,
                    )
                    logger.info("MinerU available", binary_path=str(settings.mineru_bin_path))
                except Exception as exc:
                    logger.warning(
                        "MinerU unavailable; parse will rely on Docling only",
                        error=str(exc),
                    )
        self.state = StateStore(db_path=settings.state_db_path)
        self.source_store = PostgresSourceStore(database_url=settings.database_url)
        if PipelineOpsClient is not None:
            self.ops = PipelineOpsClient.from_env(
                default_spool_db_path=str(settings.state_db_path.parent / "pipeline_ops_spool.db"),
                emitted_by="research_parser",
            )
        else:
            self.ops = _NoopPipelineOpsClient()
        self._active_run_key = None
        logger.info("Pipeline initialized")

    def process_file(
        self,
        file_id: str,
        file_name: str,
        *,
        force: bool = False,
        local_pdf_path: Path | None = None,
        relay_artifact: RelayIntakeArtifact | None = None,
    ) -> bool:
        log = logger.bind(file_id=file_id, file_name=file_name, force=force)
        max_attempts = 2
        for attempt in range(1, max_attempts + 1):
            attempt_log = log.bind(attempt=attempt, max_attempts=max_attempts)
            attempt_log.info("Starting file processing attempt")
            status, error_message = self._process_file_once(
                file_id,
                file_name,
                attempt_log,
                attempt=attempt,
                force=force,
                local_pdf_path=local_pdf_path,
                relay_artifact=relay_artifact,
            )
            if status == ProcessingStatus.COMPLETED:
                return True
            if attempt < max_attempts:
                attempt_log.warning(
                    "Processing incomplete, retrying",
                    status=status.value,
                    error=error_message,
                )
                continue
            attempt_log.error(
                "Processing failed after retries",
                status=status.value,
                error=error_message,
            )
            self.state.mark_failed(file_id, error_message or "Max retries exceeded")
            return False
        return False

    def _process_file_once(
        self,
        file_id: str,
        file_name: str,
        log: structlog.stdlib.BoundLogger,
        *,
        attempt: int,
        force: bool = False,
        local_pdf_path: Path | None = None,
        relay_artifact: RelayIntakeArtifact | None = None,
    ) -> tuple[ProcessingStatus, str | None]:
        artifact_dir = self._artifact_dir(file_id)
        document_key = make_document_key(file_id=file_id)
        document_fields = {"document_name": file_name}
        prior_state = self.state.get_state(file_id)
        self.state.start_processing(file_id, file_name)
        self.ops.emit_stage_event(
            repo_name="research_parser",
            stage_name="parser.complete",
            status="started",
            run_key=self._active_run_key,
            document_key=document_key,
            file_id=file_id,
            attempt=attempt,
            payload={"file_name": file_name},
            document_fields=document_fields,
        )

        file_path = None
        try:
            resumed = None
            if force:
                log.info("Force reparse; ignoring persisted artifacts")
            else:
                resumed = self._load_resumable_source(
                    file_id=file_id,
                    file_name=file_name,
                    artifact_dir=artifact_dir,
                    prior_state=prior_state,
                )
            if resumed is not None:
                source, parse_blocks = resumed
                self.state.update_step(file_id, "parse", True, ProcessingStatus.PARSING)
                self.state.update_step(file_id, "boilerplate", True)
                log.info("Resuming from persisted artifacts")
            else:
                try:
                    if local_pdf_path is not None:
                        file_path = local_pdf_path
                        log.info("Using relay intake PDF", path=str(local_pdf_path))
                    else:
                        with self.ops.track_stage(
                            repo_name="research_parser",
                            stage_name="parser.download",
                            run_key=self._active_run_key,
                            document_key=document_key,
                            file_id=file_id,
                            attempt=attempt,
                            payload={"file_name": file_name},
                            document_fields=document_fields,
                        ):
                            file_path = self.drive.download_file(file_id, file_name)
                except Exception as exc:
                    message = f"Download failed: {exc}"
                    log.exception("Download failed")
                    self._fail_complete(
                        document_key, file_id, file_name, attempt, document_fields, exc
                    )
                    self.state.mark_failed(file_id, message)
                    return ProcessingStatus.FAILED, message

                self.state.update_step(file_id, "parse", False, ProcessingStatus.PARSING)
                try:
                    parsed = parse_with_optional_ocr(
                        digital_backend=self.docling_backend,
                        ocr_backend_factory=lambda: self._ocr_backend(log),
                        mineru_backend=self.mineru_backend,
                        pdf_path=file_path,
                        log=log,
                        ocr_retry=self.settings.docling_ocr_retry,
                    )
                except Exception as exc:
                    message = f"Parse failed: {exc}"
                    log.error("PDF parsing failed", error=str(exc))
                    self.state.update_step(file_id, "parse", False, error_message=message)
                    self.state.mark_failed(file_id, message)
                    self._fail_complete(
                        document_key, file_id, file_name, attempt, document_fields, exc
                    )
                    return ProcessingStatus.FAILED, message

                self.state.update_step(file_id, "parse", True)
                self.ops.emit_stage_event(
                    repo_name="research_parser",
                    stage_name="parser.parse_pdf",
                    status="succeeded",
                    run_key=self._active_run_key,
                    document_key=document_key,
                    file_id=file_id,
                    attempt=attempt,
                    payload={
                        "backend": parsed.backend_name,
                        "confidence_status": parsed.confidence.status,
                        "confidence_score": parsed.confidence.score,
                        "ocr_retried": parsed.ocr_retried,
                        "ocr_retry_reasons": parsed.ocr_retry_reasons,
                    },
                    document_fields=document_fields,
                )
                try:
                    write_artifacts(artifact_dir, parsed.text_result, parsed.figures)
                    self._write_parse_artifact(artifact_dir, parsed=parsed, log=log)
                except Exception as exc:
                    log.warning("Artifact writing failed", error=str(exc))

                markdown = (
                    blocks_to_markdown(parsed.text_result.blocks, include_page_markers=True)
                    or parsed.text_result.raw_output
                    or ""
                )
                parse_blocks = list(parsed.text_result.blocks)
                try:
                    self.state.update_step(file_id, "boilerplate", False)
                    clean_text = strip_boilerplate(
                        markdown,
                        document_name=file_name,
                        source_hint=_source_from_filename(file_name),
                        log=log,
                    )
                    self.state.update_step(file_id, "boilerplate", True)
                except Exception as exc:
                    message = f"Boilerplate failed: {exc}"
                    log.warning("Boilerplate stripping failed, using raw markdown", error=str(exc))
                    clean_text = markdown
                    self.state.update_step(file_id, "boilerplate", False, error_message=message)

                self._write_clean_text_artifact(artifact_dir, clean_text, log)
                parse_blocks = filter_blocks_present_in_text(parse_blocks, clean_text)
                if relay_artifact is not None:
                    source = build_source_document_from_relay(
                        relay_artifact, file_name, clean_text
                    )
                else:
                    source = build_source_document(file_id, file_name, clean_text)

            self.state.update_step(file_id, "storage", False, ProcessingStatus.STORING)
            artifact_context = self._build_artifact_context(artifact_dir, parse_blocks)
            try:
                with self.ops.track_stage(
                    repo_name="research_parser",
                    stage_name="parser.store_source",
                    run_key=self._active_run_key,
                    document_key=document_key,
                    file_id=file_id,
                    attempt=attempt,
                    payload={"file_name": file_name},
                    document_fields=document_fields,
                ):
                    research_row = self.source_store.insert_research(
                        source,
                        file_name,
                        artifact_context=artifact_context,
                    )
            except Exception as exc:
                message = f"Storage failed: {exc}"
                log.exception("Storage failed")
                self.state.update_step(file_id, "storage", False, error_message=message)
                self.state.mark_failed(file_id, message)
                self._fail_complete(
                    document_key, file_id, file_name, attempt, document_fields, exc
                )
                return ProcessingStatus.FAILED, message

            self.state.update_step(file_id, "storage", True)
            self.state.mark_completed(file_id)
            self.ops.emit_stage_event(
                repo_name="research_parser",
                stage_name="parser.complete",
                status="succeeded",
                run_key=self._active_run_key,
                document_key=document_key,
                file_id=file_id,
                research_id=int(research_row["id"]) if research_row.get("id") is not None else None,
                document_hash=str(research_row.get("document_hash") or "") or None,
                attempt=attempt,
                payload={"file_name": file_name, "source": source.source},
                document_fields={
                    "document_name": file_name,
                    "source": source.source,
                    "source_date": source.source_date,
                    "parser_updated_at": datetime.utcnow().isoformat(),
                },
            )
            log.info(
                "File processing complete",
                source=source.source,
                text_length=len(source.full_text),
            )
            return ProcessingStatus.COMPLETED, None
        except Exception as exc:
            self._fail_complete(
                document_key, file_id, file_name, attempt, document_fields, exc
            )
            raise
        finally:
            try:
                if file_path is not None and file_path.exists():
                    os.unlink(file_path)
            except Exception:
                pass

    def _fail_complete(
        self, document_key, file_id, file_name, attempt, document_fields, exc
    ) -> None:
        self.ops.emit_stage_event(
            repo_name="research_parser",
            stage_name="parser.complete",
            status="failed",
            run_key=self._active_run_key,
            document_key=document_key,
            file_id=file_id,
            attempt=attempt,
            payload={"file_name": file_name},
            error_type=exc.__class__.__name__,
            error_text=str(exc),
            document_fields=document_fields,
        )

    def _ocr_backend(self, log):
        if not self.settings.docling_ocr_retry:
            return None
        if self.docling_ocr_backend is not None:
            return self.docling_ocr_backend
        backend = DoclingBackend(do_ocr=True)
        try:
            backend._get_converter()
        except Exception as exc:
            log.warning("Docling OCR backend unavailable", error=str(exc))
            return None
        self.docling_ocr_backend = backend
        log.info("Docling OCR backend ready")
        return backend

    def _write_parse_artifact(self, artifact_dir: Path, *, parsed, log) -> None:
        payload = {
            "backend": parsed.backend_name,
            "confidence_score": parsed.confidence.score,
            "confidence_status": parsed.confidence.status,
            "reasons": parsed.confidence.reasons,
            "ocr_retried": parsed.ocr_retried,
            "ocr_retry_reasons": parsed.ocr_retry_reasons,
            "source_page_count": parsed.text_result.source_page_count,
        }
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / _PARSE_ARTIFACT).write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("Parse artifact write failed", error=str(exc))

    def _load_parse_artifact(self, artifact_dir: Path) -> dict:
        path = artifact_dir / _PARSE_ARTIFACT
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _load_figure_manifest(self, artifact_dir: Path) -> list[dict]:
        path = artifact_dir / _FIGURES_ARTIFACT
        if not path.exists():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def _build_artifact_context(
        self,
        artifact_dir: Path,
        parse_blocks: list,
    ) -> ResearchArtifactContext:
        parse_info = self._load_parse_artifact(artifact_dir)
        return ResearchArtifactContext(
            parse_backend=parse_info.get("backend"),
            parse_confidence_score=parse_info.get("confidence_score"),
            parse_confidence_status=parse_info.get("confidence_status"),
            ocr_retried=bool(parse_info.get("ocr_retried")),
            ocr_retry_reasons=list(parse_info.get("ocr_retry_reasons") or []),
            source_page_count=parse_info.get("source_page_count"),
            raw_markdown_path=str(artifact_dir / "document.md"),
            clean_text_path=str(self._clean_text_artifact_path(artifact_dir)),
            blocks_path=str(artifact_dir / _BLOCKS_ARTIFACT),
            figure_manifest=self._load_figure_manifest(artifact_dir),
            blocks=parse_blocks,
        )

    def _artifact_dir(self, file_id: str) -> Path:
        return self.settings.artifact_base_dir / file_id

    def _clean_text_artifact_path(self, artifact_dir: Path) -> Path:
        return artifact_dir / _CLEAN_TEXT_ARTIFACT

    def _write_clean_text_artifact(self, artifact_dir: Path, clean_text: str, log) -> None:
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            content = clean_text if clean_text.endswith("\n") else f"{clean_text}\n"
            self._clean_text_artifact_path(artifact_dir).write_text(content, encoding="utf-8")
        except Exception as exc:
            log.warning("Clean text artifact write failed", error=str(exc))

    def _load_resumable_source(
        self,
        file_id: str,
        file_name: str,
        artifact_dir: Path,
        prior_state,
    ) -> tuple[SourceDocument, list] | None:
        if prior_state is None or not prior_state.parse_ok:
            return None
        path = self._clean_text_artifact_path(artifact_dir)
        if not path.exists():
            return None
        clean_text = path.read_text(encoding="utf-8")
        if not clean_text.strip():
            return None
        parse_blocks = load_blocks(artifact_dir / _BLOCKS_ARTIFACT)
        parse_blocks = filter_blocks_present_in_text(parse_blocks, clean_text)
        return build_source_document(file_id, file_name, clean_text), parse_blocks

    def process_relay_intake(self, artifact: RelayIntakeArtifact) -> bool:
        if self.state.is_relay_intake_complete(artifact.relay_key, artifact.content_hash):
            logger.info(
                "Skipping relay intake; already stored",
                relay_key=artifact.relay_key,
                content_hash=artifact.content_hash,
            )
            return False
        file_id = artifact.document_id()
        if artifact.is_html_only():
            ok = self._process_relay_html_intake(artifact, file_id=file_id)
        else:
            pdf_path = artifact.primary_pdf_path()
            if pdf_path is None or not pdf_path.is_file():
                logger.warning(
                    "Relay intake missing PDF attachment",
                    relay_key=artifact.relay_key,
                )
                return False
            ok = self.process_file(
                file_id,
                pdf_path.name,
                local_pdf_path=pdf_path,
                relay_artifact=artifact,
            )
        self.state.record_relay_intake(
            artifact.relay_key,
            content_hash=artifact.content_hash,
            document_id=file_id,
            file_id=file_id,
            storage_ok=ok,
        )
        return ok

    def _process_relay_html_intake(
        self, artifact: RelayIntakeArtifact, *, file_id: str
    ) -> bool:
        file_name = artifact.intake_file_name()
        log = logger.bind(file_id=file_id, file_name=file_name, relay_key=artifact.relay_key)
        body_text = artifact.body.strip()
        if not body_text:
            html_path = artifact.primary_html_path()
            if html_path is None or not html_path.is_file():
                log.warning("Relay HTML intake missing body and archive file")
                return False
            try:
                body_text = _plain_text_from_html(html_path.read_text(encoding="utf-8"))
            except OSError as exc:
                log.warning("Failed to read HTML intake file", error=str(exc))
                return False
        if not body_text.strip():
            log.warning("Relay HTML intake has empty body")
            return False

        self.state.start_processing(file_id, file_name)
        artifact_dir = self._artifact_dir(file_id)
        try:
            clean_text = strip_boilerplate(
                body_text,
                document_name=file_name,
                source_hint=artifact.sender_address or "relay",
                log=log,
            )
            self._write_clean_text_artifact(artifact_dir, clean_text, log)
            source = build_source_document_from_relay(artifact, file_name, clean_text)
            artifact_context = self._build_artifact_context(artifact_dir, [])
            research_row = self.source_store.insert_research(
                source,
                file_name,
                artifact_context=artifact_context,
            )
            self.state.update_step(file_id, "parse", True)
            self.state.update_step(file_id, "boilerplate", True)
            self.state.update_step(file_id, "storage", True)
            self.state.mark_completed(file_id)
            log.info(
                "Relay HTML intake stored",
                research_id=research_row.get("id"),
                text_length=len(clean_text),
            )
            return True
        except Exception as exc:
            message = f"Relay HTML intake failed: {exc}"
            log.exception("Relay HTML intake failed")
            self.state.mark_failed(file_id, message)
            return False

    def run_relay_intake_once(self) -> int:
        intake_dir = getattr(self.settings, "relay_intake_dir", None)
        if intake_dir is None:
            return 0
        adapter = RelayIntakeAdapter(intake_dir)
        processed = 0
        for artifact in adapter.list_pending():
            try:
                if self.process_relay_intake(artifact):
                    processed += 1
            except Exception as exc:
                logger.exception(
                    "Unexpected error processing relay intake",
                    relay_key=artifact.relay_key,
                    error=str(exc),
                )
        return processed

    def run_once(self, days_ago: int | None = None, since: datetime | None = None) -> int:
        logger.info("Starting polling cycle", days_ago=days_ago, since=since)
        self.ops.flush()
        run_key = self.ops.start_run(
            repo_name="research_parser",
            stage_family="parser",
            run_type="poll_cycle",
            trigger_source="drive_poll",
            stats={
                "days_ago": days_ago,
                "since": since.isoformat() if since is not None else None,
            },
        )
        self._active_run_key = run_key
        processed_count = self.run_relay_intake_once()
        try:
            retryable_partials = self.state.get_retryable_partials(
                self.settings.poll_interval_minutes
            )
            partial_ids: set[str] = set()
            for partial in retryable_partials:
                partial_ids.add(partial.file_id)
                logger.info("Retrying partial file", file_id=partial.file_id)
                try:
                    if self.process_file(partial.file_id, partial.file_name):
                        processed_count += 1
                except Exception as exc:
                    logger.exception(
                        "Unexpected error retrying partial file",
                        file_id=partial.file_id,
                    )
                    self.state.mark_failed(partial.file_id, f"Unexpected error: {exc}")

            stale_files = self.state.get_stale_in_progress(
                self.settings.stale_processing_timeout_minutes
            )
            stale_ids: set[str] = set()
            for stale in stale_files:
                stale_ids.add(stale.file_id)
                logger.warning("Retrying stale in-progress file", file_id=stale.file_id)
                try:
                    if self.process_file(stale.file_id, stale.file_name):
                        processed_count += 1
                except Exception as exc:
                    logger.exception("Unexpected error retrying stale file", file_id=stale.file_id)
                    self.state.mark_failed(stale.file_id, f"Unexpected error: {exc}")

            self.ops.emit_stage_event(
                repo_name="research_parser",
                stage_name="parser.drive_discovery",
                status="started",
                run_key=run_key,
                payload={
                    "days_ago": days_ago,
                    "since": since.isoformat() if since is not None else None,
                },
            )
            all_files = self.drive.list_pdfs(days_ago=days_ago, since=since)
            self.ops.emit_stage_event(
                repo_name="research_parser",
                stage_name="parser.drive_discovery",
                status="succeeded",
                run_key=run_key,
                payload={"discovered_count": len(all_files)},
            )
            new_files = [
                item
                for item in all_files
                if item.id not in partial_ids
                and item.id not in stale_ids
                and not self.state.is_processed(item.id)
            ]
            stats = {
                "processed_count": processed_count,
                "retryable_partials": len(retryable_partials),
                "stale_retries": len(stale_files),
                "discovered_count": len(all_files),
                "new_files_count": len(new_files),
            }
            if not new_files:
                logger.info("No new files to process", processed=processed_count)
                self.ops.update_run(run_key, status="completed", stats=stats, completed=True)
                return processed_count

            logger.info("Processing new files", count=len(new_files))
            for item in new_files:
                try:
                    if self.process_file(item.id, item.name):
                        processed_count += 1
                except Exception as exc:
                    logger.exception("Unexpected error processing file", file_id=item.id)
                    self.state.mark_failed(item.id, f"Unexpected error: {exc}")
            stats["processed_count"] = processed_count
            logger.info("Polling cycle complete", processed=processed_count)
            self.ops.update_run(run_key, status="completed", stats=stats, completed=True)
            return processed_count
        except Exception as exc:
            self.ops.update_run(
                run_key,
                status="failed",
                error_text=str(exc),
                stats={"processed_count": processed_count},
                completed=True,
            )
            raise
        finally:
            self._active_run_key = None
            self.ops.flush()
