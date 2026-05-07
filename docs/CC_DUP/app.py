from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from config import load_app_config
from context import build_system_prompt
from engine import AbortedError, Engine
from permissions import PermissionChecker
from session import SessionStore
from tools import BashTool, GlobTool, GrepTool, ReadTool

try:
    from rich.console import Console  # type: ignore[import-not-found]

    _HAS_RICH = True
except ImportError:
    _HAS_RICH = False

try:
    from _keylistener import EscListener
except ImportError:
    EscListener = None  # type: ignore[misc, assignment]


def _tool_preview(tool_name: str, tool_input: dict) -> str:
    if tool_name == "Bash":
        cmd = tool_input.get("command", "")
        return cmd[:80] + ("…" if len(cmd) > 80 else "")
    if tool_name in ("Read", "Edit", "Write"):
        fp = tool_input.get("file_path", "")
        return fp[-60:] if len(fp) > 60 else fp
    if tool_name in ("Glob", "Grep"):
        return str(tool_input.get("pattern", ""))
    return ""


def _collapsed_tool_summary(tool_names: list[str]) -> str:
    counts = Counter(tool_names)
    parts = []
    for name, n in counts.items():
        parts.append(f"{name} ×{n}" if n > 1 else name)
    return " · ".join(parts) + "…"


class _SpinnerManager:
    """Rich status spinner; no-op when Rich unavailable or plain mode."""

    def __init__(self, console: Console | None, enabled: bool):
        self._console = console
        self._enabled = enabled and console is not None
        self._status = None

    def start(self, message: str) -> None:
        self.stop()
        if not self._enabled:
            return
        self._status = self._console.status(message, spinner="dots")  # type: ignore[union-attr]
        self._status.__enter__()

    def update(self, message: str) -> None:
        if self._status is not None:
            self._status.update(status=message)

    def stop(self) -> None:
        if self._status is not None:
            self._status.__exit__(None, None, None)
            self._status = None


def run_query(
    engine: Engine,
    user_input: str,
    print_mode: bool,
    permissions: PermissionChecker | None = None,
    *,
    use_rich: bool = True,
    use_esc: bool = True,
) -> None:
    """Run one turn; interactive mode uses ESC cancel + spinner when enabled."""

    plain = print_mode or not use_rich or not _HAS_RICH
    console = Console(highlight=False) if _HAS_RICH else None

    if plain:
        try:
            for event in engine.submit(user_input):
                etype = event[0]
                if etype == "text":
                    text = event[1]
                    if print_mode:
                        print(text, end="", flush=True)
                    else:
                        print(text)
                elif etype == "tool_call":
                    _, name, inputs, _activity = event
                    print(f"[tool_call] {name} {inputs}")
                elif etype == "tool_executing":
                    _, name, _inputs, activity = event
                    print(f"[tool_executing] {name} - {activity or 'running'}")
                elif etype == "tool_result":
                    _, name, _inputs, result = event
                    status = "error" if result.is_error else "ok"
                    print(f"[tool_result:{status}] {name}\n{result.content}")
                elif etype == "error":
                    print(f"[error] {event[1]}")
                elif etype == "usage":
                    _usage = event[1]
                    if not print_mode:
                        print(
                            "[usage] "
                            f"input={getattr(_usage, 'input_tokens', 0)} "
                            f"output={getattr(_usage, 'output_tokens', 0)}"
                        )
        except (KeyboardInterrupt, AbortedError):
            engine.cancel_turn()
            print("\n[cancelled]")
        finally:
            if print_mode:
                print()
        return

    listener = None
    if use_esc and EscListener is not None:
        listener = EscListener(on_cancel=engine.abort)
        if permissions:
            permissions.set_esc_listener(listener)

    spinner = _SpinnerManager(console, enabled=True)
    pending_tools: dict[str, tuple[str, str]] = {}
    first_text = True
    streaming = False

    try:
        ctx = listener if listener is not None else _null_context()
        with ctx:
            spinner.start("Thinking…")

            for event in engine.submit(user_input):
                if streaming and listener is not None and listener.check_esc_nonblocking():
                    spinner.stop()
                    engine.cancel_turn()
                    console.print("\n[yellow]⏹ Turn cancelled (Esc)[/yellow]")
                    return

                etype = event[0]
                if etype == "text":
                    text = event[1]
                    if first_text:
                        spinner.stop()
                        if listener is not None:
                            listener.pause()
                        streaming = True
                        first_text = False
                    console.print(text, end="")

                elif etype == "waiting":
                    streaming = False
                    if listener is not None:
                        listener.resume()
                    spinner.start("Preparing tool call…")

                elif etype == "tool_call":
                    spinner.stop()
                    streaming = False
                    if listener is not None:
                        listener.pause()
                    _, tool_name, tool_input, _activity = event
                    preview = _tool_preview(tool_name, tool_input)
                    key = f"{tool_name}({preview})"
                    pending_tools[key] = (tool_name, f"↳ {key}")

                elif etype == "tool_executing":
                    _, tool_name, _tool_input, activity = event
                    if len(pending_tools) > 1:
                        names = [tn for tn, _ in pending_tools.values()]
                        spinner.start(_collapsed_tool_summary(names))
                    else:
                        _, line = next(iter(pending_tools.values()), ("", f"↳ {tool_name}"))
                        activity_text = activity or f"Running {tool_name}…"
                        spinner.start(f"{line} … {activity_text}")

                elif etype == "tool_result":
                    spinner.stop()
                    _, tool_name, tool_input, result = event
                    preview = _tool_preview(tool_name, tool_input)
                    key = f"{tool_name}({preview})"
                    _tname, line = pending_tools.pop(key, (tool_name, f"↳ {key}"))
                    if result.is_error:
                        console.print(f"[dim]{line}[/dim] [red]✗[/red]")
                        console.print(f"  [red]{result.content[:300]}[/red]")
                    else:
                        console.print(f"[dim]{line}[/dim] [green]✓[/green]")

                    if pending_tools:
                        names = [tn for tn, _ in pending_tools.values()]
                        spinner.start(_collapsed_tool_summary(names))
                    else:
                        streaming = False
                        if listener is not None:
                            listener.resume()
                        spinner.start("Thinking…")
                        first_text = True

                elif etype == "error":
                    spinner.stop()
                    console.print(f"\n[bold red]{event[1]}[/bold red]")

                elif etype == "usage":
                    _usage = event[1]
                    console.print(
                        f"[dim][usage] in={getattr(_usage, 'input_tokens', 0)} "
                        f"out={getattr(_usage, 'output_tokens', 0)}[/dim]"
                    )

            spinner.stop()
    except (KeyboardInterrupt, AbortedError):
        spinner.stop()
        if not isinstance(sys.exc_info()[1], AbortedError):
            engine.cancel_turn()
        console.print("\n[yellow]⏹ Turn cancelled[/yellow]")
        return
    finally:
        spinner.stop()
        if permissions:
            permissions.set_esc_listener(None)

    if not print_mode:
        console.print()


class _null_context:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cc-dup-mini", description="Minimal cc-mini clone")
    parser.add_argument("prompt", nargs="?", help="One-shot prompt in non-interactive mode")
    parser.add_argument("-p", "--print", action="store_true", help="Run once and print result")
    parser.add_argument(
        "--provider",
        choices=("anthropic", "openai", "mock"),
        help="LLM provider (defaults to anthropic)",
    )
    parser.add_argument("--api-key", help="Override API key")
    parser.add_argument("--base-url", help="Optional custom API base URL")
    parser.add_argument("--auto-approve", action="store_true", help="Allow all tool permissions")
    parser.add_argument("--model", help="Model name")
    parser.add_argument("--max-tokens", type=int, help="Maximum output tokens")
    parser.add_argument("--effort", choices=("low", "medium", "high"), help="Optional reasoning effort")
    parser.add_argument("--session-dir", help="Session directory path")
    parser.add_argument("--resume", metavar="SESSION", help="Resume by session id prefix or index")
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Disable Rich spinner (simple prints only)",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    cfg = load_app_config(args)

    cwd = str(Path.cwd())
    tools = [ReadTool(), GlobTool(), GrepTool(), BashTool()]
    permissions = PermissionChecker(auto_approve=cfg.auto_approve)
    session_store = SessionStore(
        cwd=cwd,
        model=cfg.model,
        session_dir=cfg.session_dir,
    )
    engine = Engine(
        tools=tools,
        system_prompt=build_system_prompt(cwd=cwd),
        permission_checker=permissions,
        provider=cfg.provider,
        api_key=cfg.api_key,
        base_url=cfg.base_url,
        model=cfg.model,
        max_tokens=cfg.max_tokens,
        effort=cfg.effort,
        session_store=session_store,
    )

    if args.resume:
        sessions = SessionStore.list_sessions(cfg.session_dir)
        target = None
        try:
            index = int(args.resume) - 1
            if 0 <= index < len(sessions):
                target = sessions[index]
        except ValueError:
            needle = args.resume.lower()
            for session in sessions:
                if session.session_id.lower().startswith(needle):
                    target = session
                    break
        if target is None:
            print(f"[warn] Session not found: {args.resume}")
        else:
            _meta, messages = SessionStore.load_session(target.session_id, cfg.session_dir)
            if messages:
                engine.set_messages(messages)
                session_store = SessionStore(
                    cwd=cwd,
                    model=cfg.model,
                    session_dir=cfg.session_dir,
                    session_id=target.session_id,
                )
                engine.set_session_store(session_store)
                print(f"[resume] loaded session {target.session_id} ({len(messages)} messages)")

    use_rich = not args.plain

    if args.print or args.prompt:
        run_query(
            engine,
            args.prompt or "",
            print_mode=True,
            permissions=permissions,
            use_rich=False,
            use_esc=False,
        )
        return

    print(
        "cc-dup-mini started | "
        f"provider={cfg.provider} | model={cfg.model} | session={session_store.session_id}"
    )
    print("Esc cancels turn (TTY). Commands: /sessions /clear . Type 'exit' to quit.")

    while True:
        try:
            user_input = input("\n> ").strip()
        except EOFError:
            print("\nGoodbye.")
            break
        except KeyboardInterrupt:
            print("\nPress Ctrl+C again or type 'exit' to quit.")
            continue

        if not user_input:
            continue

        if user_input == "/sessions":
            sessions = SessionStore.list_sessions(cfg.session_dir)
            if not sessions:
                print("[sessions] none")
                continue
            for idx, session in enumerate(sessions, start=1):
                print(f"{idx}. {session.session_id} ({session.model})")
            continue

        if user_input == "/clear":
            engine.set_messages([])
            print("[clear] conversation reset in memory (session file unchanged)")
            continue

        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break

        run_query(
            engine,
            user_input,
            print_mode=False,
            permissions=permissions,
            use_rich=use_rich,
            use_esc=True,
        )


if __name__ == "__main__":
    main()
