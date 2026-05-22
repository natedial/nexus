"""Pipeline orchestrator with fault-tolerant processing."""

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

from research_pipeline_ops import PipelineOpsClient, make_document_key

from src.config import Settings
from src.drive import DriveWatcher
from src.extraction import (
    ExtractionResult,
    Metadata,
    Theme,
    Trade,
    extract_metadata,
    extract_themes,
    extract_trades,
    strip_boilerplate,
)
from src.llm import LLMClient, load_model_config
from src.parser import (
    DoclingBackend,
    LlamaIndexBackend,
    LlamaIndexParser,
    MinerUBackend,
    blocks_to_markdown,
    write_artifacts,
)
from src.storage import StateStore, SupabaseClient
from src.storage.state import ProcessingStatus

logger = structlog.get_logger()

_DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_")
_SOURCE_PREFIXES = {
    "BARCLAYS": ("barclays",),
    "CITI": ("citi", "citigroup"),
    "DB": ("deutsche bank",),
    "GS": ("goldman sachs",),
    "JPM": ("j.p. morgan", "jp morgan", "jpmorgan", "jpm"),
    "MS": ("morgan stanley",),
}
_CLEAN_TEXT_ARTIFACT = "clean_text.md"
_EXTRACTION_ARTIFACT = "extraction.json"


class _NoopPipelineOpsClient:
    """Fallback client for tests that construct Pipeline without __init__."""

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
    """Extract YYYY-MM-DD from a filename like '2026-02-17_GS_...'."""
    m = _DATE_PREFIX_RE.match(file_name)
    if not m:
        return None
    try:
        datetime.strptime(m.group(1), "%Y-%m-%d")
        return m.group(1)
    except ValueError:
        return None


def _expected_source_aliases_from_filename(file_name: str) -> tuple[str, ...] | None:
    """Infer source aliases from filenames like '2026-02-17_GS_...'."""
    parts = file_name.split("_", 2)
    if len(parts) < 2:
        return None
    return _SOURCE_PREFIXES.get(parts[1].upper())


def _is_reusable_metadata(metadata: Metadata, file_name: str) -> bool:
    source = (metadata.source or "").strip().lower()
    if not source or source == "unknown":
        return False

    expected_aliases = _expected_source_aliases_from_filename(file_name)
    if expected_aliases is None:
        return True
    return any(alias in source for alias in expected_aliases)


class Pipeline:
    """
    Orchestrates the full research parsing pipeline.

    Fault-tolerant design: each extraction step can fail independently
    without breaking the entire pipeline. Only fully successful runs are persisted.

    Note: Synthesis is performed downstream by research_dispatcher,
    which aggregates themes/trades across multiple documents.
    """

    ops = _NoopPipelineOpsClient()
    _active_run_key: str | None = None

    def __init__(self, settings: Settings):
        self.settings = settings

        # Load model configuration from YAML
        self.model_config = load_model_config(config_path=settings.model_config_path)

        # Initialize clients
        self.drive = DriveWatcher(
            credentials_path=settings.google_credentials_path,
            folder_id=settings.google_drive_folder_id,
        )
        self.docling_backend = DoclingBackend()
        try:
            self.docling_backend._get_converter()
            logger.info("Docling available", backend="docling")
        except Exception as e:
            logger.warning(
                "Docling unavailable; will fall back to LlamaIndex",
                backend="docling",
                error=str(e),
            )
        self.llama_backend = LlamaIndexBackend(
            parser=LlamaIndexParser(api_key=settings.llamaindex_api_key)
        )
        self.mineru_backend = None
        if settings.mineru_enabled:
            if settings.mineru_bin_path is None:
                logger.warning(
                    "MinerU enabled but binary path not set; skipping",
                    backend="mineru",
                )
            elif not settings.mineru_bin_path.exists():
                logger.warning(
                    "MinerU enabled but binary path does not exist; skipping",
                    backend="mineru",
                    binary_path=str(settings.mineru_bin_path),
                )
            else:
                try:
                    self.mineru_backend = MinerUBackend(
                        binary_path=settings.mineru_bin_path,
                        cli_backend=settings.mineru_backend,
                        timeout_seconds=settings.mineru_timeout_seconds,
                    )
                    logger.info(
                        "MinerU available",
                        backend="mineru",
                        binary_path=str(settings.mineru_bin_path),
                    )
                except Exception as e:
                    logger.warning(
                        "MinerU unavailable; will fall back to LlamaIndex",
                        backend="mineru",
                        error=str(e),
                    )
        self.llm = LLMClient(
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=getattr(settings, "openai_api_key", None),
            groq_api_key=getattr(settings, "groq_api_key", None),
            deepinfra_api_key=getattr(settings, "deepinfra_api_key", None),
            openrouter_api_key=getattr(settings, "openrouter_api_key", None),
            fireworks_api_key=getattr(settings, "fireworks_api_key", None),
            together_api_key=getattr(settings, "together_api_key", None),
        )
        self.state = StateStore(db_path=settings.state_db_path)
        self.supabase = SupabaseClient(
            url=settings.supabase_url,
            key=settings.supabase_key,
        )
        self.ops = PipelineOpsClient.from_env(
            default_spool_db_path=str(settings.state_db_path.parent / "pipeline_ops_spool.db"),
            emitted_by="research_parser",
        )
        self._active_run_key: str | None = None

        logger.info("Pipeline initialized")

    def process_file(self, file_id: str, file_name: str) -> bool:
        """
        Process a single file through the pipeline.

        Returns True if processing completed successfully, False otherwise.
        """
        log = logger.bind(file_id=file_id, file_name=file_name)
        max_attempts = 2

        for attempt in range(1, max_attempts + 1):
            attempt_log = log.bind(attempt=attempt, max_attempts=max_attempts)
            attempt_log.info("Starting file processing attempt")
            status, error_message = self._process_file_once(
                file_id,
                file_name,
                attempt_log,
                attempt=attempt,
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
            # Mark as failed rather than deleting state. This prevents the
            # file from being picked up again on every poll cycle.
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
    ) -> tuple[ProcessingStatus, str | None]:
        """Process a single attempt and return its status and error summary."""
        step_errors: dict[str, str] = {}
        prior_state = self.state.get_state(file_id)
        artifact_dir = self._artifact_dir(file_id)
        document_key = make_document_key(file_id=file_id)
        document_fields = {"document_name": file_name}

        # Track processing state
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

        try:
            extraction = self._load_resumable_extraction(
                file_id=file_id,
                file_name=file_name,
                artifact_dir=artifact_dir,
                prior_state=prior_state,
                log=log,
            )
            file_path = None

            if extraction is not None:
                self.state.update_step(file_id, "parse", True, ProcessingStatus.EXTRACTING)
                if prior_state and prior_state.boilerplate_ok:
                    self.state.update_step(file_id, "boilerplate", True)
                self.ops.emit_stage_event(
                    repo_name="research_parser",
                    stage_name="parser.parse_pdf",
                    status="succeeded",
                    run_key=self._active_run_key,
                    document_key=document_key,
                    file_id=file_id,
                    attempt=attempt,
                    payload={"resumed_from_artifacts": True},
                    document_fields=document_fields,
                )
                log.info(
                    "Resuming extraction from persisted artifacts",
                    metadata_ok=extraction.metadata_ok,
                    themes_ok=extraction.themes_ok,
                    trades_ok=extraction.trades_ok,
                )
            else:
                # Step 1: Download the file
                try:
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
                except Exception as e:
                    message = f"Download failed: {e}"
                    log.exception("Download failed")
                    self.ops.emit_stage_event(
                        repo_name="research_parser",
                        stage_name="parser.complete",
                        status="failed",
                        run_key=self._active_run_key,
                        document_key=document_key,
                        file_id=file_id,
                        attempt=attempt,
                        payload={"file_name": file_name},
                        error_type=e.__class__.__name__,
                        error_text=str(e),
                        document_fields=document_fields,
                    )
                    self.state.mark_failed(file_id, message)
                    return ProcessingStatus.FAILED, message

                # Step 2: Parse PDF to markdown
                self.state.update_step(file_id, "parse", False, ProcessingStatus.PARSING)
                backend_name = "docling"
                active_backend = self.docling_backend
                try:
                    self.ops.emit_stage_event(
                        repo_name="research_parser",
                        stage_name="parser.parse_pdf",
                        status="started",
                        run_key=self._active_run_key,
                        document_key=document_key,
                        file_id=file_id,
                        attempt=attempt,
                        payload={"file_name": file_name},
                        document_fields=document_fields,
                    )
                    log.info("Parsing with Docling", backend="docling")
                    text_result = self.docling_backend.parse_text(file_path)
                    figures = self.docling_backend.extract_figures(file_path)
                except Exception as e:
                    log.warning("Docling parse failed, falling back", error=str(e))
                    if self.mineru_backend is not None:
                        backend_name = "mineru"
                        active_backend = self.mineru_backend
                        try:
                            log.info("Parsing with MinerU", backend="mineru")
                            text_result = self.mineru_backend.parse_text(file_path)
                            figures = self.mineru_backend.extract_figures(file_path)
                        except Exception as mineru_error:
                            log.warning(
                                "MinerU parse failed, falling back",
                                error=str(mineru_error),
                            )
                            backend_name = "llamaindex"
                            active_backend = self.llama_backend
                            try:
                                log.info("Parsing with LlamaIndex", backend="llamaindex")
                                text_result = self.llama_backend.parse_text(file_path)
                                figures = self.llama_backend.extract_figures(file_path)
                            except Exception as e2:
                                message = f"Parse failed: {e2}"
                                log.error("PDF parsing failed", error=str(e2))
                                self.ops.emit_stage_event(
                                    repo_name="research_parser",
                                    stage_name="parser.parse_pdf",
                                    status="failed",
                                    run_key=self._active_run_key,
                                    document_key=document_key,
                                    file_id=file_id,
                                    attempt=attempt,
                                    payload={"backend": backend_name},
                                    error_type=e2.__class__.__name__,
                                    error_text=str(e2),
                                    document_fields=document_fields,
                                )
                                self.state.update_step(
                                    file_id, "parse", False, error_message=message
                                )
                                self.state.mark_failed(file_id, message)
                                self.ops.emit_stage_event(
                                    repo_name="research_parser",
                                    stage_name="parser.complete",
                                    status="failed",
                                    run_key=self._active_run_key,
                                    document_key=document_key,
                                    file_id=file_id,
                                    attempt=attempt,
                                    payload={"file_name": file_name},
                                    error_type=e2.__class__.__name__,
                                    error_text=str(e2),
                                    document_fields=document_fields,
                                )
                                return ProcessingStatus.FAILED, message
                    else:
                        backend_name = "llamaindex"
                        active_backend = self.llama_backend
                        try:
                            log.info("Parsing with LlamaIndex", backend="llamaindex")
                            text_result = self.llama_backend.parse_text(file_path)
                            figures = self.llama_backend.extract_figures(file_path)
                        except Exception as e2:
                            message = f"Parse failed: {e2}"
                            log.error("PDF parsing failed", error=str(e2))
                            self.ops.emit_stage_event(
                                repo_name="research_parser",
                                stage_name="parser.parse_pdf",
                                status="failed",
                                run_key=self._active_run_key,
                                document_key=document_key,
                                file_id=file_id,
                                attempt=attempt,
                                payload={"backend": backend_name},
                                error_type=e2.__class__.__name__,
                                error_text=str(e2),
                                document_fields=document_fields,
                            )
                            self.state.update_step(
                                file_id, "parse", False, error_message=message
                            )
                            self.state.mark_failed(file_id, message)
                            self.ops.emit_stage_event(
                                repo_name="research_parser",
                                stage_name="parser.complete",
                                status="failed",
                                run_key=self._active_run_key,
                                document_key=document_key,
                                file_id=file_id,
                                attempt=attempt,
                                payload={"file_name": file_name},
                                error_type=e2.__class__.__name__,
                                error_text=str(e2),
                                document_fields=document_fields,
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
                    payload={"backend": backend_name},
                    document_fields=document_fields,
                )

                # Write parser artifacts (non-fatal)
                try:
                    write_artifacts(artifact_dir, text_result, figures)
                    log.info("Artifacts written", artifact_dir=str(artifact_dir))
                except Exception as e:
                    log.warning("Artifact writing failed", error=str(e))

                confidence = active_backend.confidence(text_result.blocks, figures)
                log.info(
                    "Parse confidence",
                    score=confidence.score,
                    status=confidence.status,
                    reasons=confidence.reasons,
                    backend=backend_name,
                )

                markdown = text_result.raw_output or blocks_to_markdown(text_result.blocks)
                log.info("Markdown ready", length=len(markdown), backend=backend_name)

                # Step 3: Strip boilerplate
                try:
                    self.state.update_step(
                        file_id, "boilerplate", False, ProcessingStatus.EXTRACTING
                    )
                    with self.ops.track_stage(
                        repo_name="research_parser",
                        stage_name="parser.strip_boilerplate",
                        run_key=self._active_run_key,
                        document_key=document_key,
                        file_id=file_id,
                        attempt=attempt,
                        payload={"file_name": file_name},
                        document_fields=document_fields,
                    ):
                        clean_text = strip_boilerplate(
                            self.llm,
                            markdown,
                            config=self.model_config.boilerplate,
                            log=log,
                            deterministic_only=self.settings.boilerplate_deterministic_only,
                            document_name=file_name,
                            artifact_dir=artifact_dir,
                        )
                    self.state.update_step(file_id, "boilerplate", True)
                except Exception as e:
                    message = f"Boilerplate failed: {e}"
                    log.warning(
                        "Boilerplate stripping failed, using raw markdown",
                        error=str(e),
                    )
                    clean_text = markdown
                    self.state.update_step(
                        file_id, "boilerplate", False, error_message=message
                    )
                    step_errors["boilerplate"] = message

                self._write_clean_text_artifact(artifact_dir, clean_text, log)
                log.info("Clean text ready", length=len(clean_text))

                extraction = ExtractionResult(
                    metadata=Metadata(),
                    themes=[],
                    trades=[],
                    full_text=clean_text,
                    metadata_ok=False,
                    themes_ok=False,
                    trades_ok=False,
                )

            # Step 4: Extract metadata
            try:
                if extraction.metadata_ok:
                    log.info("Reusing persisted metadata result")
                else:
                    with self.ops.track_stage(
                        repo_name="research_parser",
                        stage_name="parser.extract_metadata",
                        run_key=self._active_run_key,
                        document_key=document_key,
                        file_id=file_id,
                        attempt=attempt,
                        payload={"file_name": file_name},
                        document_fields=document_fields,
                    ):
                        extraction.metadata = extract_metadata(
                            self.llm,
                            extraction.full_text,
                            config=self.model_config.metadata,
                            log=log,
                        )
                    extraction.metadata_ok = True
                    self.state.update_step(file_id, "metadata", True)
            except Exception as e:
                message = f"Metadata failed: {e}"
                log.warning("Metadata extraction failed", error=str(e), exc_info=True)
                self.state.update_step(file_id, "metadata", False, error_message=message)
                step_errors["metadata"] = message
            finally:
                extraction.metadata.document_id = file_id
                extraction.metadata.document_uri = f"gdrive://{file_id}"
                extraction.metadata.document_link = (
                    f"https://drive.google.com/file/d/{file_id}/view"
                )
                # Always override source_date from filename (YYYY-MM-DD_ prefix)
                # which is more reliable than LLM extraction.
                date_from_name = _parse_date_from_filename(file_name)
                if date_from_name:
                    extraction.metadata.source_date = date_from_name
                    log.debug("source_date set from filename", source_date=date_from_name)
                if extraction.metadata_ok:
                    self._persist_extraction_artifact(artifact_dir, extraction, log)

            # Step 5: Extract themes
            if extraction.themes_ok:
                log.info("Reusing persisted themes result", count=len(extraction.themes))
            else:
                try:
                    with self.ops.track_stage(
                        repo_name="research_parser",
                        stage_name="parser.extract_themes",
                        run_key=self._active_run_key,
                        document_key=document_key,
                        file_id=file_id,
                        attempt=attempt,
                        payload={"file_name": file_name},
                        document_fields=document_fields,
                    ):
                        extraction.themes = extract_themes(
                            self.llm,
                            extraction.full_text,
                            config=self.model_config.themes,
                            log=log,
                        )
                    extraction.themes_ok = True
                    self.state.update_step(file_id, "themes", True)
                    self._persist_extraction_artifact(artifact_dir, extraction, log)
                except Exception as e:
                    message = f"Themes failed: {e}"
                    log.warning("Theme extraction failed", error=str(e), exc_info=True)
                    self.state.update_step(file_id, "themes", False, error_message=message)
                    step_errors["themes"] = message

            # Step 6: Extract trades
            if extraction.trades_ok:
                log.info("Reusing persisted trades result", count=len(extraction.trades))
            else:
                try:
                    with self.ops.track_stage(
                        repo_name="research_parser",
                        stage_name="parser.extract_trades",
                        run_key=self._active_run_key,
                        document_key=document_key,
                        file_id=file_id,
                        attempt=attempt,
                        payload={"file_name": file_name},
                        document_fields=document_fields,
                    ):
                        extraction.trades = extract_trades(
                            self.llm,
                            extraction.full_text,
                            config=self.model_config.trades,
                            log=log,
                        )
                    extraction.trades_ok = True
                    self.state.update_step(file_id, "trades", True)
                    self._persist_extraction_artifact(artifact_dir, extraction, log)
                except Exception as e:
                    message = f"Trades failed: {e}"
                    log.warning("Trade extraction failed", error=str(e), exc_info=True)
                    self.state.update_step(file_id, "trades", False, error_message=message)
                    step_errors["trades"] = message

            all_extraction_ok = (
                extraction.metadata_ok
                and extraction.themes_ok
                and extraction.trades_ok
            )
            if not all_extraction_ok:
                error_summary = self._format_error_summary(step_errors)
                log.warning(
                    "Extraction incomplete",
                    failed_steps=list(step_errors.keys()),
                    error=error_summary,
                )

            # Only store to Supabase when all extraction steps succeeded.
            # Partial results (empty themes/trades) should not be uploaded.
            if not all_extraction_ok:
                self.state.mark_partial(file_id, error_summary)
                self.ops.emit_stage_event(
                    repo_name="research_parser",
                    stage_name="parser.complete",
                    status="failed",
                    run_key=self._active_run_key,
                    document_key=document_key,
                    file_id=file_id,
                    attempt=attempt,
                    payload={"file_name": file_name, "failed_steps": list(step_errors.keys())},
                    error_type="partial_extraction",
                    error_text=error_summary,
                    document_fields=document_fields,
                )
                return ProcessingStatus.PARTIAL, error_summary

            # Step 7: Store in Supabase
            try:
                with self.ops.track_stage(
                    repo_name="research_parser",
                    stage_name="parser.store_supabase",
                    run_key=self._active_run_key,
                    document_key=document_key,
                    file_id=file_id,
                    attempt=attempt,
                    payload={"file_name": file_name},
                    document_fields=document_fields,
                ):
                    research_row = self.supabase.insert_research(extraction, file_name)
                self.state.update_step(file_id, "storage", True)
            except Exception as e:
                message = f"Storage failed: {e}"
                log.exception("Storage failed")
                self.state.update_step(file_id, "storage", False, error_message=message)
                self.state.mark_failed(file_id, message)
                self.ops.emit_stage_event(
                    repo_name="research_parser",
                    stage_name="parser.complete",
                    status="failed",
                    run_key=self._active_run_key,
                    document_key=document_key,
                    file_id=file_id,
                    attempt=attempt,
                    payload={"file_name": file_name},
                    error_type=e.__class__.__name__,
                    error_text=str(e),
                    document_fields=document_fields,
                )
                return ProcessingStatus.FAILED, message

            # Finalize
            self._finalize_processing(file_id, extraction)
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
                payload={
                    "file_name": file_name,
                    "source": extraction.metadata.source,
                    "theme_count": len(extraction.themes),
                    "trade_count": len(extraction.trades),
                },
                document_fields={
                    "document_name": file_name,
                    "source": extraction.metadata.source,
                    "source_date": extraction.metadata.source_date,
                    "publisher": extraction.metadata.publisher,
                    "region": extraction.metadata.region,
                    "asset_focus": extraction.metadata.asset_focus,
                    "parser_updated_at": datetime.utcnow().isoformat(),
                },
            )
            log.info(
                "File processing complete",
                source=extraction.metadata.source,
                themes=len(extraction.themes),
                trades=len(extraction.trades),
                text_length=len(extraction.full_text),
            )
            return ProcessingStatus.COMPLETED, None
        except Exception as exc:
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
            raise

        finally:
            # Clean up temp file
            try:
                if file_path is not None and file_path.exists():
                    os.unlink(file_path)
            except Exception:
                pass

    def _artifact_dir(self, file_id: str) -> Path:
        return self.settings.artifact_base_dir / file_id

    def _clean_text_artifact_path(self, artifact_dir: Path) -> Path:
        return artifact_dir / _CLEAN_TEXT_ARTIFACT

    def _extraction_artifact_path(self, artifact_dir: Path) -> Path:
        return artifact_dir / _EXTRACTION_ARTIFACT

    def _write_clean_text_artifact(
        self,
        artifact_dir: Path,
        clean_text: str,
        log: structlog.stdlib.BoundLogger,
    ) -> None:
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = self._clean_text_artifact_path(artifact_dir)
            content = clean_text if clean_text.endswith("\n") else f"{clean_text}\n"
            path.write_text(content, encoding="utf-8")
        except Exception as exc:
            log.warning("Clean text artifact write failed", error=str(exc))

    def _load_clean_text_artifact(self, artifact_dir: Path) -> str | None:
        path = self._clean_text_artifact_path(artifact_dir)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def _persist_extraction_artifact(
        self,
        artifact_dir: Path,
        extraction: ExtractionResult,
        log: structlog.stdlib.BoundLogger,
    ) -> None:
        payload = {
            "metadata_ok": extraction.metadata_ok,
            "themes_ok": extraction.themes_ok,
            "trades_ok": extraction.trades_ok,
            "metadata": (
                extraction.metadata.model_dump() if extraction.metadata_ok else None
            ),
            "themes": (
                [theme.model_dump() for theme in extraction.themes]
                if extraction.themes_ok
                else None
            ),
            "trades": (
                [trade.model_dump() for trade in extraction.trades]
                if extraction.trades_ok
                else None
            ),
        }
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            path = self._extraction_artifact_path(artifact_dir)
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        except Exception as exc:
            log.warning("Extraction artifact write failed", error=str(exc))

    def _load_resumable_extraction(
        self,
        file_id: str,
        file_name: str,
        artifact_dir: Path,
        prior_state,
        log: structlog.stdlib.BoundLogger,
    ) -> ExtractionResult | None:
        if prior_state is None or not prior_state.parse_ok:
            return None

        clean_text = self._load_clean_text_artifact(artifact_dir)
        if not clean_text:
            return None

        extraction = ExtractionResult(
            metadata=Metadata(),
            themes=[],
            trades=[],
            full_text=clean_text,
            metadata_ok=False,
            themes_ok=False,
            trades_ok=False,
        )

        path = self._extraction_artifact_path(artifact_dir)
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception as exc:
                log.warning("Extraction artifact read failed", error=str(exc))
                payload = {}

            if prior_state.metadata_ok and payload.get("metadata_ok") and payload.get("metadata"):
                metadata = Metadata.model_validate(payload["metadata"])
                if _is_reusable_metadata(metadata, file_name):
                    extraction.metadata = metadata
                    extraction.metadata_ok = True
                else:
                    log.warning(
                        "Persisted metadata source is stale or ambiguous; rerunning step",
                        source=metadata.source,
                    )
            elif prior_state.metadata_ok:
                log.warning("Metadata state found without artifact payload; rerunning step")

            if prior_state.themes_ok and payload.get("themes_ok") and payload.get("themes") is not None:
                extraction.themes = [Theme.model_validate(item) for item in payload["themes"]]
                extraction.themes_ok = True
            elif prior_state.themes_ok:
                log.warning("Themes state found without artifact payload; rerunning step")

            if prior_state.trades_ok and payload.get("trades_ok") and payload.get("trades") is not None:
                extraction.trades = [Trade.model_validate(item) for item in payload["trades"]]
                extraction.trades_ok = True
            elif prior_state.trades_ok:
                log.warning("Trades state found without artifact payload; rerunning step")

        extraction.metadata.document_id = file_id
        extraction.metadata.document_uri = f"gdrive://{file_id}"
        extraction.metadata.document_link = f"https://drive.google.com/file/d/{file_id}/view"
        date_from_name = _parse_date_from_filename(file_name)
        if date_from_name:
            extraction.metadata.source_date = date_from_name

        return extraction

    def _finalize_processing(
        self,
        file_id: str,
        extraction: ExtractionResult,
    ) -> None:
        """Mark processing as complete after a successful run."""
        self.state.mark_completed(file_id)

    @staticmethod
    def _format_error_summary(step_errors: dict[str, str]) -> str:
        if not step_errors:
            return "Unknown error"
        return "; ".join(
            f"{step}: {message}" for step, message in step_errors.items()
        )

    def run_once(
        self, days_ago: int | None = None, since: datetime | None = None
    ) -> int:
        """
        Run one polling cycle.

        Returns the number of files processed.
        """
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

        processed_count = 0
        try:
            retryable_partials = self.state.get_retryable_partials(
                self.settings.poll_interval_minutes
            )
            partial_ids: set[str] = set()
            for partial in retryable_partials:
                partial_ids.add(partial.file_id)
                logger.info(
                    "Retrying partial file",
                    file_id=partial.file_id,
                    file_name=partial.file_name,
                )
                try:
                    success = self.process_file(partial.file_id, partial.file_name)
                    if success:
                        processed_count += 1
                except Exception as e:
                    logger.exception(
                        "Unexpected error retrying partial file",
                        file_id=partial.file_id,
                    )
                    self.state.mark_failed(partial.file_id, f"Unexpected error: {e}")

            stale_files = self.state.get_stale_in_progress(
                self.settings.stale_processing_timeout_minutes
            )
            stale_ids: set[str] = set()
            for stale in stale_files:
                stale_ids.add(stale.file_id)
                logger.warning(
                    "Retrying stale in-progress file",
                    file_id=stale.file_id,
                    file_name=stale.file_name,
                )
                try:
                    success = self.process_file(stale.file_id, stale.file_name)
                    if success:
                        processed_count += 1
                except Exception as e:
                    logger.exception(
                        "Unexpected error retrying stale file",
                        file_id=stale.file_id,
                    )
                    self.state.mark_failed(stale.file_id, f"Unexpected error: {e}")

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
                f
                for f in all_files
                if f.id not in partial_ids
                and f.id not in stale_ids
                and not self.state.is_processed(f.id)
            ]

            if not new_files:
                logger.info(
                    "No new files to process",
                    stale_retries=len(stale_files),
                    processed=processed_count,
                )
                self.ops.update_run(
                    run_key,
                    status="completed",
                    stats={
                        "processed_count": processed_count,
                        "retryable_partials": len(retryable_partials),
                        "stale_retries": len(stale_files),
                        "discovered_count": len(all_files),
                        "new_files_count": 0,
                    },
                    completed=True,
                )
                return processed_count

            logger.info("Processing new files", count=len(new_files))

            for file in new_files:
                try:
                    success = self.process_file(file.id, file.name)
                    if success:
                        processed_count += 1
                except Exception as e:
                    logger.exception("Unexpected error processing file", file_id=file.id)
                    self.state.mark_failed(file.id, f"Unexpected error: {e}")

            logger.info("Polling cycle complete", processed=processed_count)
            self.ops.update_run(
                run_key,
                status="completed",
                stats={
                    "processed_count": processed_count,
                    "retryable_partials": len(retryable_partials),
                    "stale_retries": len(stale_files),
                    "discovered_count": len(all_files),
                    "new_files_count": len(new_files),
                },
                completed=True,
            )
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
