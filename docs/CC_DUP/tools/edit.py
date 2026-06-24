from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolResult


class EditTool(Tool):
    name = "Edit"
    description = (
        "Perform an exact string replacement in a text file. "
        "The old_string must match file content exactly and must be unique "
        "unless replace_all is true."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "old_string": {"type": "string"},
            "new_string": {"type": "string"},
            "replace_all": {"type": "boolean", "default": False},
        },
        "required": ["file_path", "old_string", "new_string"],
    }

    def is_read_only(self) -> bool:
        return False

    def get_activity_description(self, **kwargs):
        file_path = kwargs.get("file_path", "")
        return f"Editing {file_path}" if file_path else "Editing file"

    def execute(self, **kwargs):
        file_path = kwargs.get("file_path", "")
        old_string = kwargs.get("old_string", "")
        new_string = kwargs.get("new_string", "")
        replace_all = bool(kwargs.get("replace_all", False))

        if not file_path:
            return ToolResult("Missing file_path", is_error=True)
        if old_string == "":
            return ToolResult("Missing old_string", is_error=True)

        path = Path(file_path)
        if not path.exists():
            return ToolResult(f"File not found: {file_path}", is_error=True)

        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(content=f"Edit read error: {exc}", is_error=True)

        count = content.count(old_string)
        if count == 0:
            return ToolResult(f"old_string not found in {file_path}", is_error=True)
        if count > 1 and not replace_all:
            return ToolResult(
                f"old_string found {count} times; use replace_all=true or add more context.",
                is_error=True,
            )

        # MAMBA8A: Edit side effect. Build the new file content in memory,
        # then write it back to disk only after all match checks pass.
        new_content = (
            content.replace(old_string, new_string)
            if replace_all
            else content.replace(old_string, new_string, 1)
        )

        try:
            path.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            return ToolResult(content=f"Edit write error: {exc}", is_error=True)

        replaced = count if replace_all else 1
        return ToolResult(f"Replaced {replaced} occurrence(s) in {file_path}")
