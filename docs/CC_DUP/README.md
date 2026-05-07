# CC_DUP Minimal Runnable Template

This folder contains a minimal, runnable clone of the core loop used in `cc-mini`:

- REPL input loop
- Engine turn loop (`assistant -> tool_use -> tool_result -> assistant`)
- Tool abstraction (`Read`, `Grep`, `Bash`)
- Permission checks
- Session persistence (JSONL)
- Real provider support (`anthropic` / `openai`) + mock fallback
- API key fallback loading from environment and `~/.bashrc`
- API retry and retryable error handling
- Read-only tool parallel execution batches
- Session resume support (`--resume`)
- `load_dotenv()` (`.env` in cwd) + `~/.bashrc` key fallbacks
- Rich status spinner + **Esc to cancel** (TTY) when not using `--plain`
- `build_system_prompt` with working directory
- `/clear` to reset in-memory messages; `/sessions` to list JSONL sessions
- `Glob` tool (read-only, can run in parallel with other read-only tools)

## Quick Start

```bash
python docs/CC_DUP/app.py --provider anthropic
```

Run single prompt:

```bash
python docs/CC_DUP/app.py --provider anthropic --print "hello"
```

Resume from a previous session:

```bash
python docs/CC_DUP/app.py --provider anthropic --resume 1
```

or by prefix:

```bash
python docs/CC_DUP/app.py --provider anthropic --resume 20260413
```

Enable all write/bash approvals:

```bash
python docs/CC_DUP/app.py --provider anthropic --auto-approve
```

Mock mode (no network):

```bash
python docs/CC_DUP/app.py --provider mock
```

Interactive REPL without Rich spinner (plain text only):

```bash
python docs/CC_DUP/app.py --provider anthropic --plain
```

Create a `.env` in the project root or cwd (same convention as cc-mini):

```bash
ANTHROPIC_API_KEY=...
# or ANTHROPIC_AUTH_TOKEN + ANTHROPIC_BASE_URL for compatible endpoints
```

## API Key Resolution Order

For `--provider anthropic`, key names are checked in order:

1. `ANTHROPIC_API_KEY`
2. `ANTHROPIC_AUTH_TOKEN`
3. `CC_DUP_API_KEY`
4. `CC_MINI_API_KEY`
5. exported values parsed from `~/.bashrc` with same names

For `--provider openai`, key names:

1. `OPENAI_API_KEY`
2. `CC_DUP_API_KEY`
3. `CC_MINI_API_KEY`
4. exported values parsed from `~/.bashrc` with same names

If you see:

`No API key found for provider=openai`

set one of:

- `OPENAI_API_KEY`
- `CC_DUP_API_KEY`

in your shell environment or `~/.bashrc`.

`base_url` resolution order:

1. `--base-url`
2. `CC_DUP_BASE_URL`
3. provider-specific env (`ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`)
4. exported values parsed from `~/.bashrc`

## Built-in Tool Triggers (Mock LLM)

In `--provider mock`, the model uses simple prefixes in user input:

- `/tool read <path>`
- `/tool grep <pattern> :: <path>`
- `/tool bash <command>`

Example:

```text
/tool read README.md
```

The engine will emit tool events, execute the tool, feed `tool_result` back to the model, and then output the final assistant response.

## Additional REPL Commands

- `/sessions` : list local saved sessions
