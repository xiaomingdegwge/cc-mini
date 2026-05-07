from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolResult


class ReadTool(Tool):
    name = "Read"
    description = "Read text content from a file path."
    input_schema = {
        "type": "object",
        "properties": {"file_path": {"type": "string"}},
        "required": ["file_path"],
    }

    def get_activity_description(self, **kwargs):
        return "Reading file"

    def execute(self, **kwargs):
        file_path = kwargs.get("file_path", "")
        if not file_path:
            return ToolResult("Missing file_path", is_error=True)
        try:
            content = Path(file_path).read_text(encoding="utf-8")
            if not content:
                content = "File is empty."
            return ToolResult(content=content)
        except Exception as exc:
            return ToolResult(content=f"Read error: {exc}", is_error=True)
