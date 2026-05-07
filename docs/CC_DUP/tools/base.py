from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


class Tool:
    name: str = "Tool"
    description: str = ""
    input_schema: dict[str, Any] = {"type": "object", "properties": {}}

    def to_api_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }

    def is_read_only(self) -> bool:
        return True

    def get_activity_description(self, **kwargs: Any) -> str | None:
        return None

    def execute(self, **kwargs: Any) -> ToolResult:
        raise NotImplementedError("Tool.execute() must be implemented by subclasses.")
