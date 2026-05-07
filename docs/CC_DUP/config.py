from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


@dataclass(frozen=True)
class AppConfig:
    provider: str
    api_key: str | None
    base_url: str | None
    model: str
    max_tokens: int
    effort: str | None
    auto_approve: bool
    session_dir: str


def _default_model(provider: str) -> str:
    if provider == "openai":
        return "gpt-4o-mini"
    if provider == "mock":
        return "mock-sonnet"
    return "claude-sonnet-4-20250514"


def load_app_config(args: argparse.Namespace) -> AppConfig:
    provider = (args.provider or os.getenv("CC_DUP_PROVIDER", "anthropic")).strip().lower()
    if provider not in {"anthropic", "openai", "mock"}:
        raise ValueError(f"Unsupported provider: {provider}")

    model = args.model or os.getenv("CC_DUP_MODEL", _default_model(provider))
    max_tokens = args.max_tokens or int(os.getenv("CC_DUP_MAX_TOKENS", "1024"))
    session_dir = args.session_dir or os.getenv("CC_DUP_SESSION_DIR", ".cc_dup_sessions")
    bashrc_exports = _read_bashrc_exports(os.path.expanduser("~/.bashrc"))
    api_key = args.api_key or _resolve_api_key(provider, bashrc_exports)
    base_url = args.base_url or _resolve_base_url(provider, bashrc_exports)
    effort = args.effort or os.getenv("CC_DUP_EFFORT")
    return AppConfig(
        provider=provider,
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_tokens=max_tokens,
        effort=effort,
        auto_approve=bool(args.auto_approve),
        session_dir=session_dir,
    )


def _resolve_api_key(provider: str, bashrc_exports: dict[str, str]) -> str | None:
    candidates = []
    if provider == "openai":
        candidates = ["CC_DUP_API_KEY", "OPENAI_API_KEY"]
    elif provider == "anthropic":
        candidates = ["CC_DUP_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"]
    else:
        candidates = ["CC_DUP_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_AUTH_TOKEN"]

    for key in candidates:
        value = os.getenv(key)
        if value:
            return value
    for key in candidates:
        value = bashrc_exports.get(key)
        if value:
            return value
    return None


def _resolve_base_url(provider: str, bashrc_exports: dict[str, str]) -> str | None:
    candidates = ["CC_DUP_BASE_URL"]
    if provider == "openai":
        candidates.append("OPENAI_BASE_URL")
    if provider == "anthropic":
        candidates.append("ANTHROPIC_BASE_URL")

    for key in candidates:
        value = os.getenv(key)
        if value:
            return value
    for key in candidates:
        value = bashrc_exports.get(key)
        if value:
            return value
    return None


def _read_bashrc_exports(path: str) -> dict[str, str]:
    exports: dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
    except Exception:
        return exports

    pattern = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = pattern.match(line)
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        exports[key] = value
    return exports
