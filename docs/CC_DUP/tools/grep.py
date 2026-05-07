from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolResult


class GrepTool(Tool):
    name = "Grep"
    description = "Search lines containing a pattern in a text file."
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "file_path": {"type": "string"},
        },
        "required": ["pattern", "file_path"],
    }

    def get_activity_description(self, **kwargs):
        return "Searching file content"

    def execute(self, **kwargs):
        pattern = kwargs.get("pattern", "")
        file_path = kwargs.get("file_path", "")
        if not pattern or not file_path:
            return ToolResult("Missing pattern or file_path", is_error=True)

        try:
            text = Path(file_path).read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(content=f"Grep read error: {exc}", is_error=True)

        lines = text.splitlines()
        hits = []
        for idx, line in enumerate(lines, start=1):
            if pattern in line:
                hits.append(f"{idx}:{line}")

        if not hits:
            return ToolResult(content="No matches found.")
        return ToolResult(content="\n".join(hits[:200]))
