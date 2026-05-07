from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from tools.base import Tool

if TYPE_CHECKING:
    from _keylistener import EscListener

PermissionBehavior = Literal["allow", "deny"]


class PermissionChecker:
    """Read-only tools are auto-allowed; mutating tools need confirmation."""

    def __init__(self, auto_approve: bool = False):
        self._auto_approve = auto_approve
        self._always_allow: set[str] = set()
        self._esc_listener: EscListener | None = None

    def set_esc_listener(self, listener: EscListener | None) -> None:
        self._esc_listener = listener

    def check(self, tool: Tool, inputs: dict) -> PermissionBehavior:
        if tool.is_read_only():
            return "allow"
        if self._auto_approve or tool.name in self._always_allow:
            return "allow"
        return self._prompt_user(tool, inputs)

    def _prompt_user(self, tool: Tool, inputs: dict) -> PermissionBehavior:
        if self._esc_listener is not None:
            self._esc_listener.pause()
        try:
            print(f"\n[permission] Tool={tool.name}")
            for key, value in inputs.items():
                print(f"  - {key}: {value}")
            choice = input("Allow? [y]es / [n]o / [a]lways: ").strip().lower()
            if choice == "a":
                self._always_allow.add(tool.name)
                return "allow"
            if choice == "y":
                return "allow"
            return "deny"
        finally:
            if self._esc_listener is not None:
                self._esc_listener.resume()
