"""Tool registry for agent tool use."""

from pathlib import Path
from typing import Any, Callable


class ToolRegistry:
    """Registry for managing agent tools.

    Loads tool schemas and handles tool invocation.
    """

    def __init__(self, schema_path: Path | None = None):
        self._schema_path = schema_path
        self._handlers: dict[str, Callable] = {}
        self._schemas: dict[str, dict] = {}

    def load_schema(self, schema_path: Path) -> None:
        """Load tool schemas from JSON file."""
        pass

    def register_handler(self, name: str, handler: Callable) -> None:
        """Register a handler for a tool."""
        pass

    def get_schema(self, name: str) -> dict[str, Any] | None:
        """Get the schema for a tool by name."""
        pass

    def invoke(
        self, name: str, input_data: dict[str, Any], timeout: float = 30.0
    ) -> dict[str, Any]:
        """Invoke a tool by name with the given input."""
        pass

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        pass
