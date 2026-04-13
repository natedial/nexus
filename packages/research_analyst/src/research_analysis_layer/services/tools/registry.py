"""Tool registry for agent tool use."""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError

logger = logging.getLogger(__name__)

_CORPUS_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_SCHEMA_PATH = (
    _CORPUS_ROOT / "research-store" / "distill_tool" / "tool_schema.json"
)

_rate_limit_semaphore: threading.Semaphore | None = None
_rate_limit_lock = threading.Lock()


def get_rate_limiter(max_concurrent: int = 4) -> threading.Semaphore:
    """Get or create the process-wide rate limiting semaphore."""
    global _rate_limit_semaphore
    if _rate_limit_semaphore is None:
        with _rate_limit_lock:
            if _rate_limit_semaphore is None:
                _rate_limit_semaphore = threading.Semaphore(max_concurrent)
    return _rate_limit_semaphore


class ToolRegistry:
    """Registry for managing agent tools.

    Loads tool schemas and handles tool invocation with timeout,
    rate limiting, and error handling.
    """

    def __init__(
        self,
        schema_path: Path | None = None,
        rate_limit: int = 4,
    ):
        self._schema_path = schema_path or _DEFAULT_SCHEMA_PATH
        self._handlers: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._rate_limiter = get_rate_limiter(rate_limit)
        if self._schema_path.exists():
            self.load_schema(self._schema_path)

    def load_schema(self, schema_path: Path) -> None:
        """Load tool schemas from JSON file."""
        try:
            with open(schema_path) as f:
                schemas = json.load(f)
            for tool_spec in schemas:
                name = tool_spec.get("name")
                if name:
                    self._schemas[name] = tool_spec
            logger.info(
                "Loaded %d tool schemas from %s", len(self._schemas), schema_path
            )
        except Exception as e:
            logger.error("Failed to load tool schema from %s: %s", schema_path, e)
            raise

    def register_handler(self, name: str, handler: Callable) -> None:
        """Register a handler for a tool."""
        if name not in self._schemas:
            raise ValueError(
                f"Tool {name} not found in schema. Available: {list(self._schemas.keys())}"
            )
        self._handlers[name] = handler
        logger.debug("Registered handler for tool: %s", name)

    def get_schema(self, name: str) -> dict[str, Any] | None:
        """Get the schema for a tool by name."""
        return self._schemas.get(name)

    def get_all_schemas(self) -> list[dict[str, Any]]:
        """Get all tool schemas for passing to LLM."""
        return list(self._schemas.values())

    def validate_input(
        self, tool_name: str, input_data: dict[str, Any]
    ) -> tuple[bool, str]:
        """Validate tool input against schema.

        Returns:
            (is_valid, error_message)
        """
        schema = self._schemas.get(tool_name)
        if not schema:
            return False, f"Unknown tool: {tool_name}"

        params = schema.get("parameters", {})
        required = params.get("required", [])
        properties = params.get("properties", {})

        for field in required:
            if field not in input_data:
                return False, f"Missing required field: {field}"

        return True, ""

    def invoke(
        self, name: str, input_data: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Invoke a tool by name with the given input.

        Applies rate limiting, input validation, timeout, and error handling.
        Returns a dict with either 'result' or 'error' key.
        """
        if name not in self._handlers:
            return {
                "is_error": True,
                "content": f"Tool {name} has no registered handler",
            }

        is_valid, error_msg = self.validate_input(name, input_data)
        if not is_valid:
            return {
                "is_error": True,
                "content": f"Input validation failed: {error_msg}",
            }

        handler = self._handlers[name]

        with self._rate_limiter:
            future = self._executor.submit(handler, input_data)
            try:
                result = future.result(timeout=timeout)
                return {"is_error": False, "content": result}
            except TimeoutError:
                logger.warning("Tool %s timed out after %ds", name, timeout)
                return {
                    "is_error": True,
                    "content": f"Tool execution timed out after {timeout}s",
                }
            except Exception as e:
                logger.exception("Tool %s raised exception", name)
                return {"is_error": True, "content": f"Tool error: {str(e)}"}

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._schemas.keys())

    def shutdown(self) -> None:
        """Shutdown the thread pool executor."""
        self._executor.shutdown(wait=True)
