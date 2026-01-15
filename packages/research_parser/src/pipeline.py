"""Pipeline orchestrator with fault-tolerant processing."""

import os
from pathlib import Path

import structlog

from src.config import Settings
from src.drive import DriveWatcher
from src.extraction import (
    ExtractionResult,
    Metadata,
    extract_metadata,
    extract_themes,
    extract_trades,
    strip_boilerplate,
)
from src.llm import LLMClient, load_model_config
from src.parser import LlamaIndexParser
from src.storage import StateStore, SupabaseClient
from src.storage.state import ProcessingStatus

logger = structlog.get_logger()


class Pipeline:
    """
    Orchestrates the full research parsing pipeline.

    Fault-tolerant design: each extraction step can fail independently
    without breaking the entire pipeline. Partial results are saved.

    Note: Synthesis is performed downstream by research_dispatcher,
    which aggregates themes/trades across multiple documents.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

        # Load model configuration from YAML
        self.model_config = load_model_config()

        # Initialize clients
        self.drive = DriveWatcher(
            credentials_path=settings.google_credentials_path,
            folder_id=settings.google_drive_folder_id,
        )
        self.parser = LlamaIndexParser(api_key=settings.llamaindex_api_key)
        self.llm = LLMClient(
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=getattr(settings, 'openai_api_key', None),
        )
        self.state = StateStore(db_path=settings.state_db_path)
        self.supabase = SupabaseClient(
            url=settings.supabase_url,
            key=settings.supabase_key,
        )

        logger.info("Pipeline initialized")

    def process_file(self, file_id: str, file_name: str) -> bool:
        """
        Process a single file through the pipeline.

        Returns True if processing completed (even partially), False if fatal error.
        """
        log = logger.bind(file_id=file_id, file_name=file_name)
        log.info("Starting file processing")

        # Track processing state
        self.state.start_processing(file_id, file_name)

        # Step 1: Download the file
        try:
            file_path = self.drive.download_file(file_id, file_name)
        except Exception as e:
            log.exception("Download failed")
            self.state.mark_failed(file_id, f"Download failed: {e}")
            return False

        try:
            # Step 2: Parse PDF to markdown
            self.state.update_step(file_id, "parse", False, ProcessingStatus.PARSING)
            parse_result = self.parser.parse(file_path)

            if not parse_result.markdown:
                log.error("PDF parsing failed", error=parse_result.error)
                self.state.update_step(file_id, "parse", False)
                self.state.mark_failed(file_id, f"Parse failed: {parse_result.error}")
                return False

            self.state.update_step(file_id, "parse", True)
            markdown = parse_result.markdown

            # Step 3: Strip boilerplate
            try:
                self.state.update_step(
                    file_id, "boilerplate", False, ProcessingStatus.EXTRACTING
                )
                clean_text = strip_boilerplate(
                    self.llm,
                    markdown,
                    config=self.model_config.boilerplate,
                    log=log,
                    deterministic_only=self.settings.boilerplate_deterministic_only,
                )
                self.state.update_step(file_id, "boilerplate", True)
            except Exception as e:
                log.warning("Boilerplate stripping failed, using raw markdown", error=str(e))
                clean_text = markdown
                self.state.update_step(file_id, "boilerplate", False)

            # Initialize result with defaults
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
                extraction.metadata = extract_metadata(
                    self.llm,
                    clean_text,
                    config=self.model_config.metadata,
                    log=log,
                )
                extraction.metadata_ok = True
                self.state.update_step(file_id, "metadata", True)
            except Exception as e:
                log.warning("Metadata extraction failed", error=str(e))
                self.state.update_step(file_id, "metadata", False)

            # Step 5: Extract themes
            try:
                extraction.themes = extract_themes(
                    self.llm,
                    clean_text,
                    config=self.model_config.themes,
                    log=log,
                )
                extraction.themes_ok = True
                self.state.update_step(file_id, "themes", True)
            except Exception as e:
                log.warning("Theme extraction failed", error=str(e))
                self.state.update_step(file_id, "themes", False)

            # Step 6: Extract trades
            try:
                extraction.trades = extract_trades(
                    self.llm,
                    clean_text,
                    config=self.model_config.trades,
                    log=log,
                )
                extraction.trades_ok = True
                self.state.update_step(file_id, "trades", True)
            except Exception as e:
                log.warning("Trade extraction failed", error=str(e))
                self.state.update_step(file_id, "trades", False)

            # Step 7: Store in Supabase
            try:
                self.supabase.insert_research(extraction, file_name)
                self.state.update_step(file_id, "storage", True)
            except Exception as e:
                log.exception("Storage failed")
                self.state.update_step(file_id, "storage", False)
                # Storage failure is still partial success
                self._finalize_processing(file_id, extraction, storage_failed=True)
                return True

            # Finalize
            self._finalize_processing(file_id, extraction, storage_failed=False)
            return True

        finally:
            # Clean up temp file
            try:
                if file_path.exists():
                    os.unlink(file_path)
            except Exception:
                pass

    def _finalize_processing(
        self,
        file_id: str,
        extraction: ExtractionResult,
        storage_failed: bool,
    ) -> None:
        """Mark processing as complete or partial based on step results."""
        all_ok = all([
            extraction.metadata_ok,
            extraction.themes_ok,
            extraction.trades_ok,
            not storage_failed,
        ])

        if all_ok:
            self.state.mark_completed(file_id)
        else:
            failed_steps = []
            if not extraction.metadata_ok:
                failed_steps.append("metadata")
            if not extraction.themes_ok:
                failed_steps.append("themes")
            if not extraction.trades_ok:
                failed_steps.append("trades")
            if storage_failed:
                failed_steps.append("storage")

            self.state.mark_partial(
                file_id,
                f"Failed steps: {', '.join(failed_steps)}",
            )

    def run_once(self, days_ago: int | None = None) -> int:
        """
        Run one polling cycle.

        Returns the number of files processed.
        """
        logger.info("Starting polling cycle", days_ago=days_ago)

        # Get new files from Drive
        all_files = self.drive.list_pdfs(days_ago=days_ago)
        new_files = [f for f in all_files if not self.state.is_processed(f.id)]

        if not new_files:
            logger.info("No new files to process")
            return 0

        logger.info("Processing new files", count=len(new_files))

        processed_count = 0
        for file in new_files:
            try:
                success = self.process_file(file.id, file.name)
                if success:
                    processed_count += 1
            except Exception as e:
                logger.exception("Unexpected error processing file", file_id=file.id)
                self.state.mark_failed(file.id, f"Unexpected error: {e}")

        logger.info("Polling cycle complete", processed=processed_count)
        return processed_count
