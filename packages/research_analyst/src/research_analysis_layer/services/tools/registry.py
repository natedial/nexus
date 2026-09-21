"""Tool registry for agent tool use."""

from __future__ import annotations

import json
import logging
import re
import threading
from pathlib import Path
from typing import Any, Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError

logger = logging.getLogger(__name__)

_ANALYST_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_SCHEMA_PATH = _ANALYST_ROOT / "schemas" / "corpus_tool_schema.json"

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
        self._schema_path = (
            schema_path if schema_path is not None else _DEFAULT_SCHEMA_PATH
        )
        self._handlers: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}
        self._executor = ThreadPoolExecutor(max_workers=4)
        self._rate_limiter = get_rate_limiter(rate_limit)
        self._budget_lock = threading.Lock()
        self._remaining_invocations: int | None = None

        if schema_path is not None:
            if not self._schema_path.exists():
                raise ValueError(
                    f"Tool schema not found at specified path: {self._schema_path}"
                )
            self.load_schema(self._schema_path)
        else:
            if not self._schema_path.exists():
                raise ValueError(
                    f"Tool schema not found at default path: {self._schema_path}. "
                    f"Ensure schemas/corpus_tool_schema.json exists in research_analyst."
                )
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

    def register_schema(self, schema: dict[str, Any]) -> None:
        """Register an extra tool schema without changing the distill JSON file.

        Analyst-local tools (argument-graph queries, etc.) live here so the
        corpus search schema JSON stays limited to research_search tools.
        """
        name = schema.get("name")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tool schema requires a non-empty name")
        self._schemas[name] = schema
        logger.debug("Registered schema for tool: %s", name)

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
        if not isinstance(input_data, dict):
            return False, "Tool input must be an object"

        params = schema.get("parameters", {})
        required = params.get("required", [])
        properties = params.get("properties", {})

        for field in required:
            if field not in input_data:
                return False, f"Missing required field: {field}"

        for field in input_data:
            if field not in properties:
                return False, f"Unknown field: {field}"

        for field, value in input_data.items():
            field_schema = properties.get(field, {})
            is_valid, error = self._validate_value(value, field_schema, path=field)
            if not is_valid:
                return False, error

        return True, ""

    def set_invocation_budget(self, limit: int | None) -> None:
        """Set a shared tool invocation budget for the current run."""
        with self._budget_lock:
            self._remaining_invocations = limit

    def clear_invocation_budget(self) -> None:
        """Clear any shared tool invocation budget."""
        self.set_invocation_budget(None)

    def _consume_budget(self) -> tuple[bool, str]:
        """Atomically consume one tool invocation from the shared budget."""
        with self._budget_lock:
            if self._remaining_invocations is None:
                return True, ""
            if self._remaining_invocations <= 0:
                return False, "Tool invocation budget exhausted"
            self._remaining_invocations -= 1
        return True, ""

    def _validate_value(
        self, value: Any, schema: dict[str, Any], *, path: str
    ) -> tuple[bool, str]:
        """Validate a value against a small JSON-schema-like subset."""
        expected_type = schema.get("type")
        if expected_type is None:
            return True, ""

        allowed_types = (
            expected_type if isinstance(expected_type, list) else [expected_type]
        )
        if value is None:
            if "null" in allowed_types:
                return True, ""
            return False, f"{path} must not be null"

        primitive_validators = {
            "string": lambda item: isinstance(item, str),
            "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
            "number": lambda item: isinstance(item, (int, float))
            and not isinstance(item, bool),
            "boolean": lambda item: isinstance(item, bool),
            "object": lambda item: isinstance(item, dict),
            "array": lambda item: isinstance(item, list),
        }

        matched_type = None
        for candidate in allowed_types:
            validator = primitive_validators.get(candidate)
            if validator and validator(value):
                matched_type = candidate
                break

        if matched_type is None:
            expected = ", ".join(str(item) for item in allowed_types)
            return False, f"{path} must be of type {expected}"

        if matched_type == "string":
            min_length = schema.get("minLength")
            if min_length is not None and len(value) < min_length:
                return False, f"{path} must be at least {min_length} characters"
            max_length = schema.get("maxLength")
            if max_length is not None and len(value) > max_length:
                return False, f"{path} must be at most {max_length} characters"
            pattern = schema.get("pattern")
            if pattern and re.fullmatch(pattern, value) is None:
                return False, f"{path} does not match required pattern"

        if matched_type in {"integer", "number"}:
            minimum = schema.get("minimum")
            if minimum is not None and value < minimum:
                return False, f"{path} must be >= {minimum}"
            maximum = schema.get("maximum")
            if maximum is not None and value > maximum:
                return False, f"{path} must be <= {maximum}"

        if matched_type == "array":
            item_schema = schema.get("items")
            if item_schema:
                for idx, item in enumerate(value):
                    is_valid, error = self._validate_value(
                        item, item_schema, path=f"{path}[{idx}]"
                    )
                    if not is_valid:
                        return False, error

        if matched_type == "object":
            nested_properties = schema.get("properties", {})
            required = schema.get("required", [])
            allow_additional = schema.get("additionalProperties", True)
            for field in required:
                if field not in value:
                    return False, f"{path}.{field} is required"
            if nested_properties:
                for field, item in value.items():
                    if field in nested_properties:
                        is_valid, error = self._validate_value(
                            item,
                            nested_properties[field],
                            path=f"{path}.{field}",
                        )
                        if not is_valid:
                            return False, error
                    elif allow_additional is False:
                        return False, f"Unknown field: {path}.{field}"

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

        allowed, budget_error = self._consume_budget()
        if not allowed:
            return {
                "is_error": True,
                "content": budget_error,
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
