"""Main entry point for the research parser service."""

import signal
import sys
from datetime import datetime

import structlog
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import get_settings
from src.pipeline import Pipeline

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


class ResearchParserService:
    """Main service that runs the research parser on a schedule."""

    def __init__(self):
        self.settings = get_settings()
        self.pipeline = Pipeline(self.settings)
        self.scheduler = BlockingScheduler()
        self._running = True

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Shutdown signal received", signal=signum)
        self._running = False
        self.scheduler.shutdown(wait=False)
        sys.exit(0)

    def _poll_job(self):
        """Job that runs on each polling interval."""
        if not self._running:
            return

        try:
            processed = self.pipeline.run_once()
            logger.info("Poll complete", processed_count=processed)
        except Exception:
            logger.exception("Error in polling job")

    def run(self):
        """Start the service."""
        logger.info(
            "Starting Research Parser Service",
            poll_interval_minutes=self.settings.poll_interval_minutes,
            drive_folder=self.settings.google_drive_folder_id,
        )

        # Run once immediately on startup
        self._poll_job()

        # Schedule recurring polls
        self.scheduler.add_job(
            self._poll_job,
            trigger=IntervalTrigger(minutes=self.settings.poll_interval_minutes),
            id="poll_drive",
            name="Poll Google Drive for new PDFs",
            next_run_time=datetime.now(),
        )

        try:
            logger.info("Scheduler started")
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Service stopped")


def main():
    """Entry point."""
    service = ResearchParserService()
    service.run()


if __name__ == "__main__":
    main()
