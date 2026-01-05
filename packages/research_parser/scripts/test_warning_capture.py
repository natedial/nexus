#!/usr/bin/env python3
"""Test warning capture system."""

import structlog

from src.storage import warning_processor

# Configure structlog with warning processor
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


def main():
    """Test warning capture with different scenarios."""
    print("Testing warning capture system...\n")

    # Test 1: Warning with document context (should be captured)
    print("Test 1: Warning with document context")
    logger = structlog.get_logger()
    bound_logger = logger.bind(
        file_id="test-123",
        file_name="Test Document.pdf"
    )
    bound_logger.warning(
        "Failed to parse themes JSON",
        error="Invalid JSON format",
        raw='{"incomplete": "json...',
    )
    print("  ✓ Warning logged (should create file in data/warnings/)\n")

    # Test 2: Warning without document context (should NOT be captured)
    print("Test 2: Warning without document context")
    logger.warning("Generic warning without file context")
    print("  ✓ Warning logged (should NOT create file)\n")

    # Test 3: Info log with document context (should NOT be captured)
    print("Test 3: Info log with document context")
    bound_logger.info("Processing complete", status="success")
    print("  ✓ Info logged (should NOT create file)\n")

    # Test 4: Multiple warnings for same document
    print("Test 4: Multiple warnings for same document")
    bound_logger.warning("Metadata extraction failed", error="Timeout")
    bound_logger.warning("Trade extraction failed", error="Rate limit")
    print("  ✓ Warnings logged (should create 2 more files)\n")

    print("Test complete! Check data/warnings/ for captured warnings.")


if __name__ == "__main__":
    main()
