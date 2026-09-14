"""Main entry point for the research parser service."""

import signal
import sys
import argparse
from datetime import datetime, timezone

import structlog
from apscheduler.schedulers import SchedulerNotRunningError
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.config import get_settings
from src.pipeline import Pipeline
from src.storage import warning_processor

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        warning_processor,  # Capture warnings to files
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
        self._since = self._parse_since(self.settings.drive_since_date)

        # Register signal handlers for graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_shutdown)
        signal.signal(signal.SIGINT, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Shutdown signal received", signal=signum)
        self._running = False
        try:
            if self.scheduler.running:
                self.scheduler.shutdown(wait=False)
        except SchedulerNotRunningError:
            logger.debug("Scheduler shutdown skipped; scheduler was not running")
        except Exception as exc:
            logger.warning("Scheduler shutdown raised unexpectedly", error=str(exc))
        sys.exit(0)

    @staticmethod
    def _parse_since(value: str | None):
        if not value:
            return None
        try:
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning("Invalid since date; expected YYYY-MM-DD", since=value)
            return None

    def _poll_job(self):
        """Job that runs on each polling interval."""
        if not self._running:
            return

        try:
            processed = self.pipeline.run_once(since=self._since)
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

        # Catch up on recent files if configured
        if self._since is None and self.settings.catchup_days > 0:
            logger.info("Running catchup", days=self.settings.catchup_days)
            try:
                processed = self.pipeline.run_once(days_ago=self.settings.catchup_days)
                logger.info("Catchup complete", processed_count=processed)
            except Exception:
                logger.exception("Error in catchup")
        elif self._since is not None and self.settings.catchup_days > 0:
            logger.info(
                "Skipping catchup because --since or drive_since_date is set",
                since=self._since,
                catchup_days=self.settings.catchup_days,
            )

        # Run once immediately on startup
        self._poll_job()

        # Schedule recurring polls (no next_run_time to avoid duplicating
        # the manual poll above — first scheduled run after poll_interval)
        self.scheduler.add_job(
            self._poll_job,
            trigger=IntervalTrigger(minutes=self.settings.poll_interval_minutes),
            id="poll_drive",
            name="Poll Google Drive for new PDFs",
        )

        try:
            logger.info("Scheduler started")
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Service stopped")


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description="Run the Research Parser Service")
    parser.add_argument(
        "--catchup",
        type=int,
        default=None,
        help="Process files from the last N days on startup, then continue polling",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="Only consider PDFs created on/after this date (YYYY-MM-DD, UTC)",
    )
    args = parser.parse_args()

    service = ResearchParserService()
    if args.catchup is not None:
        service.settings.catchup_days = args.catchup
    if args.since is not None:
        service.settings.drive_since_date = args.since
        service._since = service._parse_since(args.since)
    service.run()


if __name__ == "__main__":
    main()
