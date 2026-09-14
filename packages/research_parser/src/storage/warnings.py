"""Warning capture and storage system."""

import json
from datetime import datetime
from pathlib import Path

import structlog

# Default warnings directory
WARNINGS_DIR = Path(__file__).parent.parent.parent / "data" / "warnings"


class WarningCapture:
    """Captures and stores warnings to individual files per document."""

    def __init__(self, warnings_dir: Path | None = None):
        self.warnings_dir = warnings_dir or WARNINGS_DIR
        self.warnings_dir.mkdir(parents=True, exist_ok=True)

    def capture(self, event_dict: dict) -> None:
        """
        Capture a warning event and store it to a file.

        Args:
            event_dict: The structlog event dictionary
        """
        # Only process warnings
        if event_dict.get("log_level") != "warning":
            return

        # Get document context from bound logger
        file_name = event_dict.get("file_name")
        file_id = event_dict.get("file_id")

        # If no document context, skip (not a document-related warning)
        if not file_name:
            return

        # Create a safe filename from the document name
        safe_name = self._sanitize_filename(file_name)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        warning_file = self.warnings_dir / f"{safe_name}_{timestamp}.txt"

        # Build warning content
        warning_content = self._format_warning(event_dict)

        # Write to file
        with open(warning_file, "w") as f:
            f.write(warning_content)

    def _sanitize_filename(self, filename: str) -> str:
        """Convert filename to safe filesystem name."""
        # Remove extension
        name = Path(filename).stem

        # Replace problematic characters
        safe = name.replace(" ", "_").replace("/", "_").replace("\\", "_")

        # Remove non-alphanumeric except underscore and dash
        safe = "".join(c for c in safe if c.isalnum() or c in ("_", "-"))

        # Truncate to reasonable length
        return safe[:100]

    def _format_warning(self, event_dict: dict) -> str:
        """Format warning event into readable text."""
        lines = []

        # Header
        lines.append("=" * 80)
        lines.append("WARNING CAPTURED")
        lines.append("=" * 80)
        lines.append("")

        # Timestamp
        timestamp = event_dict.get("timestamp", datetime.utcnow().isoformat())
        lines.append(f"Timestamp: {timestamp}")
        lines.append("")

        # Document info
        lines.append("Document Information:")
        lines.append(f"  File Name: {event_dict.get('file_name', 'Unknown')}")
        lines.append(f"  File ID:   {event_dict.get('file_id', 'Unknown')}")
        lines.append("")

        # Warning message
        event = event_dict.get("event", "No message")
        lines.append(f"Warning: {event}")
        lines.append("")

        # Additional context (error messages, raw data, etc.)
        context_keys = [k for k in event_dict.keys() if k not in (
            "event", "log_level", "timestamp", "file_name", "file_id",
            "logger", "positional_args", "exc_info", "stack_info"
        )]

        if context_keys:
            lines.append("Context:")
            for key in context_keys:
                value = event_dict[key]
                # Format value nicely
                if isinstance(value, (dict, list)):
                    value_str = json.dumps(value, indent=2)
                else:
                    value_str = str(value)

                lines.append(f"  {key}:")
                # Indent multi-line values
                for line in value_str.split("\n"):
                    lines.append(f"    {line}")
                lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)


# Global instance
_warning_capture = None


def get_warning_capture() -> WarningCapture:
    """Get or create the global warning capture instance."""
    global _warning_capture
    if _warning_capture is None:
        _warning_capture = WarningCapture()
    return _warning_capture


def warning_processor(logger, method_name, event_dict):
    """
    Structlog processor that captures warnings to files.

    This should be added to the structlog processor chain.
    """
    if event_dict.get("log_level") == "warning":
        try:
            capture = get_warning_capture()
            capture.capture(event_dict)
        except Exception:
            # Don't let warning capture break logging
            pass

    return event_dict
