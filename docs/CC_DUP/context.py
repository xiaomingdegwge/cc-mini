from __future__ import annotations


def build_system_prompt(*, cwd: str) -> str:
    return (
        "You are cc-dup-mini, a minimal coding assistant aligned with cc-mini.\n"
        f"Working directory: {cwd}\n"
        "When answering questions about the codebase, use Read, Glob, or Grep "
        "before guessing. Use Bash only when necessary."
    )
