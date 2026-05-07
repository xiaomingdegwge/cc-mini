from __future__ import annotations

import glob as glob_module
from pathlib import Path

from .base import Tool, ToolResult


class GlobTool(Tool):
    name = "Glob"
    description = (
        "Fast file pattern matching. Supports globs like '**/*.py'. "
        "Returns paths sorted by modification time (newest first)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string"},
        },
        "required": ["pattern"],
    }

    def is_read_only(self) -> bool:
        return True

    def get_activity_description(self, **kwargs) -> str | None:
        pattern = kwargs.get("pattern", "")
        return f"Glob {pattern}" if pattern else None

    def execute(self, **kwargs) -> ToolResult:
        pattern = str(kwargs.get("pattern", ""))
        path = str(kwargs.get("path", "."))
        base = Path(path).resolve()
        if not base.exists():
            return ToolResult(content=f"Directory not found: {path}", is_error=True)
        matches = glob_module.glob(pattern, root_dir=str(base), recursive=True)
        sorted_paths = sorted(matches, key=lambda p: (base / p).stat().st_mtime, reverse=True)
        if not sorted_paths:
            return ToolResult(content="No files matched.")
        return ToolResult(content="\n".join(sorted_paths))
