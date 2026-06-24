from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolResult


class WriteTool(Tool):
    name = "Write"
    description = "Write complete text content to a file, creating parent directories when needed."
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "content": {"type": "string"},
        },
        "required": ["file_path", "content"],
    }

    def is_read_only(self) -> bool:
        return False

    def get_activity_description(self, **kwargs):
        file_path = kwargs.get("file_path", "")
        return f"Writing {file_path}" if file_path else "Writing file"

    def execute(self, **kwargs):
        file_path = kwargs.get("file_path", "")
        content = kwargs.get("content", "")
        if not file_path:
            return ToolResult("Missing file_path", is_error=True)

        path = Path(file_path)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(content), encoding="utf-8")
        except Exception as exc:
            return ToolResult(content=f"Write error: {exc}", is_error=True)

        line_count = str(content).count("\n") + (1 if content and not str(content).endswith("\n") else 0)
        return ToolResult(f"Wrote {line_count} line(s) to {file_path}")
