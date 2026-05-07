from __future__ import annotations

import subprocess

from .base import Tool, ToolResult


class BashTool(Tool):
    name = "Bash"
    description = "Execute a shell command."
    input_schema = {
        "type": "object",
        "properties": {"command": {"type": "string"}},
        "required": ["command"],
    }

    def is_read_only(self) -> bool:
        return False

    def get_activity_description(self, **kwargs):
        return "Running shell command"

    def execute(self, **kwargs):
        command = kwargs.get("command", "")
        if not command:
            return ToolResult("Missing command", is_error=True)
        try:
            completed = subprocess.run(
                command,
                shell=True,
                check=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
            )
            output = completed.stdout or ""
            if completed.returncode != 0:
                return ToolResult(
                    content=f"[exit {completed.returncode}]\n{output}",
                    is_error=True,
                )
            return ToolResult(content=output if output else "(no output)")
        except Exception as exc:
            return ToolResult(content=f"Bash error: {exc}", is_error=True)
