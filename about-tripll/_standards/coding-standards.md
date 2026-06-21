# tripll — Coding Standards

**Status:** **READY** — normative repo-wide conventions (style, types, async, testing, security, Git). No separate architecture Q&A file.

Standards and conventions for all code written in tripll. Follow these consistently across the entire codebase.

> **Provenance:** These standards are inherited from the [sevn.bot](https://github.com/sevn-bot/sevn.bot) project tripll was extracted from. Some illustrative code examples still reference sevn modules (e.g. `sevn.gateway`); read them as generic patterns — the **rules** apply unchanged to `src/tripll/`.

## Contents

- [Language & Runtime](#language--runtime)
- [Style & Formatting](#style--formatting)
- [Type Hints](#type-hints)
- [Async](#async)
- [Error Handling](#error-handling)
- [Logging](#logging)
- [Comments & Documentation](#comments--documentation)
- [Data Models](#data-models)
- [Testing](#testing)
- [Project Structure Conventions](#project-structure-conventions)
- [Dependencies](#dependencies)
- [Makefiles & Command Surface](#makefiles--command-surface)
- [Security](#security)
- [Tool Output Conventions](#tool-output-conventions)
- [Git & Commits](#git--commits)
- [Config File Convention](#config-file-convention)
- [Enforcement](#enforcement)

---

## Language & Runtime

- **Python 3.12+** — use modern syntax (match/case, type unions with `|`, etc.)
- **Package manager:** uv (not pip directly)
- **Build system:** hatchling
- **Source layout:** `src/tripll/` (src layout, not flat)

**Examples (shell).** Day-to-day commands go through the root `Makefile` (see [Makefiles & Command Surface](#makefiles--command-surface)). Raw `uv` is shown here for reference — in practice you call `make <target>`:

```bash
# Bootstrap a fresh checkout (uv install, deps, hooks)
make setup

# Install / sync deps after pulling
make install                 # wraps: uv sync

# Run the gateway against the local workspace
make run                     # wraps: uv run python -m sevn.gateway.main

# Full local check (what CI runs)
make ci                      # fans out to: lint typecheck test doctest security

# Add a new runtime dependency (one-off, no target needed)
uv add httpx
```

---

## Style & Formatting

### Formatter / Linter

- **Ruff** for both linting and formatting
- Line length: **100** characters (same as the predecessor project)
- Target version: `py312`

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "UP",   # pyupgrade
    "B",    # flake8-bugbear
    "SIM",  # flake8-simplify
    "RUF",  # ruff-specific rules
    "ASYNC",  # flake8-async (blocking calls in async def, unsafe asyncio APIs)
    "PT",     # flake8-pytest-style (fixture naming, raises=, warns=)
    "TCH",    # flake8-type-checking (TYPE_CHECKING imports, lazy typing)
    "PIE",    # flake8-pie (unnecessary passes, duplicate literals)
]
ignore = [
    "E501",   # line too long (handled by formatter)
    "B008",   # function call in default argument (common in FastAPI)
]

[tool.ruff.lint.isort]
known-first-party = ["tripll"]

# Optional: per-directory overrides (example)
# [tool.ruff.lint.per-file-ignores]
# "tests/**" = ["S101"]  # assert allowed in tests if you enable tryceratops S rules later
```

**Improving Ruff over time**

- **Turn rules on in layers.** Start from the baseline `select` above, run `uv run ruff check --statistics`, fix the noisiest buckets, then add stricter families (for example `PTH` for pathlib migration, `TRY` for try/except hygiene, `RET` for return consistency) once the tree is clean.
- **Use `per-file-ignores` for tests and scripts.** Legitimate patterns in tests (asserts, monkeypatch) often conflict with rules meant for production code; scope ignores narrowly instead of disabling rules globally.
- **Prefer `extend-select` in downstream packages** if a subpackage needs extra rules without forking the whole shared config.
- **Keep Ruff and the pre-commit `rev` aligned** so local hooks and CI use the same rule set.
- **Run format as part of lint workflow** (`ruff format` / `ruff check` together) so line length and style never drift.

### Naming Conventions

| Element | Convention | Example |
|---------|-----------|---------|
| Modules | `snake_case.py` | `tool_executor.py` |
| Classes | `PascalCase` | `ToolExecutor`, `RlmTriager` |
| Functions / methods | `snake_case` | `build_tool_executor()` |
| Constants | `UPPER_SNAKE_CASE` | `TELEGRAM_MAX_TEXT_LENGTH` |
| Private | Leading underscore | `_parse_message()`, `_seen_updates` |
| Type aliases | `PascalCase` | `TranscriptCallback` |
| Config keys (JSON) | `snake_case` | `use_code_graph_rag` |
| Env variables | `UPPER_SNAKE_CASE` | `SEVN_WORKSPACE` |

### Imports

- Use `from __future__ import annotations` at the top of every module
- Group imports: stdlib, third-party, first-party (`tripll.*`)
- Ruff isort handles ordering automatically
- Prefer explicit imports over `*` imports
- Use `TYPE_CHECKING` block for import-only-at-type-check-time types

**Good vs bad (import grouping):**

```python
# Good — stdlib, third-party, first-party, then TYPE_CHECKING
from __future__ import annotations

import json
from pathlib import Path

import httpx
from loguru import logger

from tripll.agent.tool_executor import Tool

# Bad — wildcard, wrong order, missing future annotations
from tripll.agent.tool_executor import *
import httpx
import json
```

```python
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from tripll.agent.tool_executor import Tool, ToolDefinition

if TYPE_CHECKING:
    from tripll.gateway.session_manager import Session
```

---

## Type Hints

- **All public functions and methods must have type hints** (parameters and return type)
- Private/internal methods: type hints encouraged but not mandatory for trivial cases
- Use `|` union syntax, not `Union[]` — e.g., `str | None`, `int | float`
- Use `dict[str, Any]` not `Dict[str, Any]` (lowercase generics)
- Use `list[str]` not `List[str]`
- Dataclasses or Pydantic models for structured data — avoid raw dicts for internal APIs
- `Any` is acceptable for external API boundaries (webhook payloads, LLM responses)

**Examples:**

```python
# Good — modern builtins and unions
def normalize_ids(raw: str | None) -> list[str]:
    ...

def payload_summary(data: dict[str, Any]) -> str:
    ...

# Bad — legacy typing aliases (avoid)
from typing import Dict, List, Optional

def bad_ids(raw: Optional[str]) -> List[str]:
    ...

def bad_summary(data: Dict[str, Any]) -> str:
    ...
```

---

## Async

- **async by default** — all I/O operations must be async
- Use `asyncio` primitives, not threading (except for CPU-bound work or SDK constraints like claude-agent subprocess)
- `httpx.AsyncClient` for HTTP calls (not `requests`)
- `aiosqlite` for database operations
- Never use `asyncio.run()` inside async code — use `await` or `create_task()`

**Examples:**

```python
import asyncio

import httpx


async def fetch_json(url: str) -> dict[str, object]:
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()


async def background_flush() -> None:
    """Example background task (implement real flush logic in production)."""
    await asyncio.sleep(0)


async def run_pipeline() -> None:
    # Good — await from async context
    _data = await fetch_json("https://api.example.com/v1/status")

    # Good — fire-and-forget when appropriate
    _ = asyncio.create_task(background_flush())

    # Bad — blocks the event loop and breaks when already in a running loop
    # _data = asyncio.run(fetch_json("https://api.example.com/v1/status"))
```

---

## Error Handling

- **Fail loudly in development, gracefully in production**
- Use specific exception types, not bare `except Exception`
- Log errors with `logger.error(...)` or `logger.warning(...)` — include context
- Never silently swallow exceptions — at minimum log them
- For tool execution: catch, log, return error string to the LLM (don't crash the agent loop)
- For channel adapters: catch, log, continue (one failed message shouldn't stop polling)

```python
# Good — log specific failures, preserve chains when wrapping or re-raising
try:
    result = await self._api_call("sendMessage", **kwargs)
except httpx.HTTPStatusError as e:
    logger.warning(f"Telegram send failed: {e.response.status_code}")
    raise
except Exception as e:
    logger.error(f"Unexpected error sending Telegram message: {e}")
    raise RuntimeError("Telegram sendMessage failed") from e

# Bad
try:
    result = await self._api_call("sendMessage", **kwargs)
except:
    pass
```

---

## Logging

- **Loguru** — not stdlib `logging`
- Use structured log messages with context: `logger.info(f"[{session_id}] processing message from {user_id}")`
- Prefer `logger.bind(session_label=..., user_id=...)` (or equivalent structured fields) when you need grepable, machine-parseable context alongside the human-readable prefix pattern
- Session context prefix pattern: `[{session_short_id}*{scope}*@{username}*{topic}]`
- Log levels:
  - `debug` — detailed internal state (tool calls, token counts, cache hits)
  - `info` — normal operations (message received, reply sent, session created)
  - `warning` — recoverable issues (API retry, fallback triggered, threshold exceeded)
  - `error` — failures requiring attention (tool crash, provider down, DB error)
- Never log secrets, API keys, or full message content at `info` level

**Example:**

```python
from loguru import logger

session_label = f"[{session_short_id}*{scope}*@{username}*{topic}]"
logger.info(f"{session_label} message received from user_id={user_id}")
logger.debug(f"{session_label} tool_calls={len(tool_calls)} tokens_in={tokens_in}")
# Never: logger.info(f"token={api_key}")  # secrets belong in env/secret stores only
```

---

## Comments & Documentation

### Comments

- **Code should be self-explanatory** — don't comment obvious things
- Comment the **why**, not the **what**
- Use comments for: non-obvious business logic, workarounds, performance trade-offs, security considerations
- No commented-out code — delete it (git has history)
- TODO format: `# TODO(username): description` or `# TODO: description` if short-lived

```python
# Good — explains WHY
# Telegram has a 4090 char limit (UTF-16 code units); keep under for safety
TELEGRAM_MAX_TEXT_LENGTH = 4090

# Bad — restates the code
# Set max text length to 4090
TELEGRAM_MAX_TEXT_LENGTH = 4090
```

### Docstrings

- **All functions, methods, and classes** get docstrings — no exceptions
- Always use `"""triple double quotes"""` — never single quotes or other styles
- Use `r"""raw triple double quotes"""` if the docstring contains backslashes
- One-line docstrings for simple cases, multi-line for anything non-trivial

### Module-level docstring (required on every `.py` file)

```python
"""Telegram channel adapter — Bot API with topics, inline keyboards, callbacks.

Module: sevn.channels.telegram
Depends: sevn.gateway.channel_router, httpx, loguru

Exports:
    Classes:
        TelegramAdapter — Poll/webhook transport, send/chunk, callbacks.
        TelegramTopicRouter — Maps forum topics to internal scopes.
    Functions:
        build_telegram_adapter — Construct adapter from workspace ``tripll.json``.
        parse_webhook_update — Normalize Bot API update dicts for the gateway.
    Private:
        _coerce_chat_id — Narrow raw chat identifiers (implementation detail).
"""
```

**Module docstring schema:**

```python
"""<One-line summary of what this module does.>

Module: <full dotted module path>
Depends: <key internal modules and third-party libraries this module uses>

Exports:
    Classes:
        <ClassName> — <one-line description>
        <ClassName> — <one-line description>
    Functions:
        <function_name> — <one-line description>
        <function_name> — <one-line description>
    Private:
        <_function_name> — <one-line description>  # optional subsection; omit if nothing private worth listing
"""
```

List **every** public class and public function defined in the module under `Exports:` (plus `Private:` when useful). Descriptions are short phrases after an em dash. Omit empty subsections. This inventory is validated by `scripts/check_docstrings.py` (see [Enforcement](#enforcement)).

### Class docstring template

```python
class TelegramAdapter(ChannelAdapter):
    """Telegram Bot API adapter with polling and webhook support.

    Handles message parsing, sending (with chunking and Markdown fallback),
    inline keyboard callbacks, file uploads, and long-polling.

    Attributes:
        config: Telegram adapter configuration (token, policies, topics).

    Example:
        adapter = TelegramAdapter(config)
        await adapter.start_polling(on_message)
    """
```

**Class docstring schema:**

```python
class ClassName(BaseClass):
    """<One-line summary.>

    <Detailed description of what this class does, its role in the system,
    and any important behavior or constraints.>

    Attributes:
        <name>: <description of public attribute.>
        <name>: <description of public attribute.>

    Example:
        <Short usage example showing typical instantiation and use.>
    """
```

### Function / method docstring template

```python
async def send(self, message: OutgoingMessage) -> list[str]:
    """Send message to Telegram, chunking if over length limit.

    Splits text at 4090 chars, retries without Markdown parse_mode on
    400 errors, and attaches inline keyboards to the first chunk only.

    Args:
        message (OutgoingMessage): Outgoing message with text, metadata
            (chat_id, topic_id, inline_keyboard), and channel routing info.

    Returns:
        list[str]: Telegram message_id strings for each sent chunk.

    Raises:
        RuntimeError: If Telegram API returns ok=false after all retries.

    Examples:
        >>> msg = OutgoingMessage(user_id="123", text="Hello", metadata={"chat_id": "123"})
        >>> ids = await adapter.send(msg)
        >>> ids
        ["456"]

        >>> long_msg = OutgoingMessage(user_id="123", text="A" * 5000, metadata={"chat_id": "123"})
        >>> ids = await adapter.send(long_msg)
        >>> len(ids)
        2
    """
```

**Function docstring schema:**

```python
def function_name(self, arg1: type, arg2: type = default) -> return_type:
    """<One-line summary of what this function does.>

    <Optional detailed description — include if the behavior is not obvious
    from the summary. Explain non-obvious logic, side effects, or constraints.>

    Args:
        <arg_name> (<type>): <Description of the argument. For complex types,
            describe the expected structure or valid values.>
        <arg_name> (<type>, optional): <Description.> Defaults to <default>.

    Returns:
        <type>: <Description of return value. For complex types, describe
        the structure. Omit this section for functions returning None with
        no meaningful side effect.>

    Raises:
        <ExceptionType>: <When and why this exception is raised.>
        <Omit this section if the function doesn't raise exceptions.>

    Examples:
        >>> result = function_name(arg1_value, arg2_value)
        >>> result
        <expected output>

        >>> result = function_name(edge_case_value)
        >>> result
        <expected output for edge case>
    """
```

**Args format rules:**
- Always include the type in parentheses: `arg_name (type):`
- For optional args with defaults: `arg_name (type, optional): Description. Defaults to X.`
- For complex types, use the full type hint: `message (dict[str, Any]):`
- For union types: `value (str | None):`

### One-line docstrings

Use for simple, self-evident properties and trivial getters only:

```python
@property
def name(self) -> str:
    """Return the channel adapter name."""
    return "telegram"
```

For functions with parameters, always use multi-line even if simple:

```python
def _chunk_text(text: str, max_len: int = 4090) -> list[str]:
    """Split text into chunks under max_len, breaking at newlines when possible.

    Args:
        text (str): Text to split.
        max_len (int, optional): Maximum chunk length. Defaults to 4090.

    Returns:
        list[str]: List of text chunks, each under max_len.

    Examples:
        >>> _chunk_text("short text")
        ["short text"]

        >>> chunks = _chunk_text("A" * 5000, max_len=4090)
        >>> len(chunks)
        2
    """
```

### Private methods

Private methods (`_prefixed`) also get full docstrings:

```python
def _parse_message(self, message: dict[str, Any], raw: dict[str, Any]) -> IncomingMessage | None:
    """Parse a Telegram message dict into an IncomingMessage.

    Handles text, captions, attachments, reply-to context, topic routing,
    and DM policy / allowlist filtering. Returns None if message should
    be ignored (policy rejection, missing user_id).

    Args:
        message (dict[str, Any]): Telegram message object from the update.
            Must contain at minimum 'from.id' and 'chat.id' keys.
        raw (dict[str, Any]): Full raw update payload (preserved for debugging).

    Returns:
        IncomingMessage | None: Normalized message, or None if filtered out
            by DM policy, allowlist, or missing user_id.

    Examples:
        >>> msg = {"from": {"id": 123}, "chat": {"id": 456}, "text": "hello"}
        >>> result = adapter._parse_message(msg, {"update_id": 1, "message": msg})
        >>> result.text
        "hello"

        >>> msg = {"from": {"id": 999}, "chat": {"id": 456}, "text": "hi"}
        >>> adapter._parse_message(msg, {})  # user not in allowlist
        None
    """
```

### Raw docstrings

Use `r"""..."""` when backslashes appear (regex patterns, file paths):

```python
def match_command(text: str) -> bool:
    r"""Check if text matches the command pattern.

    Matches strings like `/command` or `/command@botname`.
    Pattern: ``^/[a-z_]+(@\w+)?$``

    Args:
        text (str): Input text to check.

    Returns:
        bool: True if text matches a bot command pattern.

    Examples:
        >>> match_command("/status")
        True

        >>> match_command("/config@sevnbot")
        True

        >>> match_command("hello")
        False
    """
```

### Docstring rules summary

| Rule | Requirement |
|------|------------|
| All classes | `"""..."""` docstring required |
| All public methods | `"""..."""` docstring required |
| All private methods | `"""..."""` docstring required |
| All standalone functions | `"""..."""` docstring required |
| All modules (files) | Module-level `"""..."""` required |
| Quote style | Always `"""triple double quotes"""` |
| Backslashes in docstring | Use `r"""raw triple double quotes"""` |
| One-liner | Only for properties/trivial getters with no parameters |
| Args section | Required if function has parameters (except `self`/`cls`) |
| Args format | `name (type):` or `name (type, optional): ... Defaults to X.` |
| Returns section | Required if return value is not None or is meaningful |
| Returns format | `type: description` |
| Raises section | Required if function explicitly raises exceptions |
| Examples section | **Required** for all functions — at least one runnable `>>>` block; **syntactically** valid under `scripts/check_docstrings.py`; **semantically** valid under `make doctest` (see below) |
| Module `Exports:` | Required — lists every public class/function (and optional `Private:`) with one-line descriptions |

**Examples (runnable, still required)**

- Every function and method docstring must include an `Examples:` section with at least one `>>>` block.
- **Lint-time syntax:** `make lint` runs `scripts/check_docstrings.py`, which parses each `Examples:` region with the stdlib `doctest` parser and `compile()`s every `>>>` command block. Invalid Python in an example is a **merge failure** (catch typos before `make doctest`).
- **Examples must be behavioral at lint time:** `scripts/check_docstrings.py` rejects `>>> callable(my_function)` / `True` as the only example. Show a real call with arguments (or construction for `__init__`). Under `src/tripll/cli/**`, doctests must call the documented function by name. Prefer input → output examples for stable public APIs.
- **Run-time / semantic truth:** Examples must also execute successfully under `make doctest` (which runs `pytest --doctest-modules src/tripll scripts/check_docstrings.py`). That is the guardrail for correct expected output, imports, and side effects. Fix drift when APIs change; do not leave stale expected output.
- Async examples may use `asyncio.run(...)` inside the doctest block (only in docstrings / tests, never inside production async call stacks).

---

## Data Models

- **Pydantic `BaseModel`** for configuration and API-facing models (validation, serialization)
- **`dataclass`** for internal data structures (lighter weight, no validation overhead)
- **`pydantic_settings.BaseSettings`** (package `pydantic-settings`) for settings loaded from env and files — not `BaseModel` alone
- Avoid raw dicts for anything that crosses module boundaries — use a typed model

**Pydantic + mypy (`pydantic.mypy` plugin):** blocking `make typecheck` runs mypy `strict` with the plugin enabled (`pyproject.toml` `[tool.pydantic-mypy]`). Expect `init_forbid_extra`, `init_typed`, and `warn_required_dynamic_aliases` on new/changed models. Legacy `AliasChoices` fields may carry narrow `# TODO(ci-quality): burn down` module overrides until the tree is clean — do not weaken global `strict`.

**Dataclasses and synthesized methods:** document the **class** with Attributes / role as usual. Do **not** duplicate docstrings for synthesized `__init__` / `__repr__` / comparison methods unless you implement a **custom** `__init__` or other method in source; the checker treats the class docstring as sufficient for `@dataclass`-generated signatures.

```python
# Config — Pydantic
class TelegramConfig(BaseModel):
    bot_token: str
    use_webhooks: bool = False
    webhook_url: str = ""

# Internal state — dataclass
@dataclass
class VoiceSession:
    session_id: str
    config: VoiceConfig
    active: bool = True
```

---

## Testing

- **pytest** + **pytest-asyncio** with `asyncio_mode = "auto"` (see `[tool.pytest.ini_options]` below)
- **`asyncio_mode = "auto"`** — async tests are scheduled without marking every test with `@pytest.mark.asyncio`. Keep the marker **only** when you need an explicit loop scope / policy override, or when a file opts out of auto mode; do not double-wrap tests unnecessarily.
- Test directory mirrors source: `tests/tools/test_file_ops.py` for `src/tripll/tools/file_ops.py`
- Test naming: `test_<function_or_behavior>()`
- Use fixtures for shared setup (workspace paths, mock sessions, etc.)
- Mock external services (Telegram API, LLM providers) — never hit real APIs in tests
- Integration tests (DB, Docker sandbox) in a separate `tests/integration/` directory
- Aim for tests on all tools, channel adapters, and RLM pipeline

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**Example test (async, mocked client):**

```python
from unittest.mock import AsyncMock

import httpx
import pytest


async def fetch_status(client: httpx.AsyncClient, url: str) -> dict[str, object]:
    response = await client.get(url)
    response.raise_for_status()
    return response.json()


# @pytest.mark.asyncio optional when asyncio_mode = auto; kept here for explicit policy in templates.
@pytest.mark.asyncio
async def test_fetch_status_returns_json() -> None:
    fake_response = AsyncMock()
    fake_response.json.return_value = {"ok": True}
    fake_response.raise_for_status = AsyncMock(return_value=None)

    client = AsyncMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(return_value=fake_response)

    result = await fetch_status(client, "https://api.example.com/v1/status")
    assert result == {"ok": True}
```

---

## Project Structure Conventions

- One class per file when the class is large (>200 lines) — e.g., each tool in its own file
- Related small classes can share a file — e.g., `ToolDefinition`, `ToolCall`, `ToolResult` in `base.py`
- `__init__.py` should be minimal — re-exports only, no logic
- Constants at module level, not inside classes (unless class-specific)
- Configuration defaults in `config.py`, not scattered across modules

**Example layout:**

```text
src/tripll/
  __init__.py
  gateway/
    __init__.py
    main.py
  channels/
    telegram/
      adapter.py
tests/
  gateway/
    test_main.py
  channels/
    telegram/
      test_adapter.py
```

---

## Dependencies

- Core dependencies: minimal and pinned to minimum version (`>=x.y.z`)
- Optional features as extras: `[dev]`, `[anthropic]`, `[browser]`, etc.
- Never add a dependency for something that can be done in <20 lines of stdlib code
- Prefer well-maintained libraries with async support
- Pin exact versions only for known-problematic libraries (e.g., `litellm==x.y.z`)

**Example (`pyproject.toml` fragment):**

```toml
[project]
dependencies = [
    "httpx>=0.27.0",
    "loguru>=0.7.0",
    "pydantic>=2.0.0",
    "pydantic-settings>=2.0.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0.0", "pytest-asyncio>=0.24.0", "ruff>=0.8.0"]
```

---

## Makefiles & Command Surface

**Normative.** Every recurring command in tripll — setup, install, lint, format, typecheck, test, doctest, security scan, run, build, deploy, clean — is exposed as a **`make` target**. Raw `uv` / `pre-commit` / `pytest` / `docker` / `gh` invocations live **inside the Makefile**, not in docs, READMEs, CI YAML, or a contributor's muscle memory. The Makefile is the single source of truth for "how do I do X in this repo?".

### Why

- **Discoverability.** `make help` lists every target with a one-line description; new contributors (and agents) don't have to grep history or guess flag combinations.
- **Local / CI parity.** CI workflows shell out to `make <target>` so the exact command on a laptop is the exact command on GitHub Actions. No "works on my machine" because a flag drifted.
- **Refactor safety.** When a tool changes (`uv` → something else, `mypy` → `ty`, `pytest` plugins added), targets are edited in one place. Docs and contributors don't break.
- **Agent-friendly.** Coding agents (Claude, Codex, etc.) can be told "run `make ci`" and don't need to re-derive the command stack each session.

### Layout

- **Root `Makefile`** — canonical top-level targets. Required at minimum:
  - `help` — prints all targets with their docstrings (default goal)
  - `setup` — fresh-machine bootstrap (uv install, hooks, pre-commit install, secrets template)
  - `install` — `uv sync` + extras
  - `lint` — `ruff check`
  - `format` — `ruff format`
  - `typecheck` — `mypy --strict` (or `ty` / `basedpyright`)
  - `test` — `pytest`
  - `doctest` — `pytest --doctest-modules`
  - `security` — `bandit` + secret scan + `uv pip audit`
  - `precommit` — `pre-commit run --all-files`
  - `ci` — fans out to `lint typecheck test doctest security` (one entry point CI calls)
  - `run` — start the gateway against the local workspace
  - `clean` — drop caches, build artifacts, `__pycache__`, etc.
- **Per-area Makefiles** — every high-level folder that has its own command surface ships a Makefile and is **included from the root** (or invoked via a recursive target). Examples:
  - `infra/Makefile` — `tunnel-up`, `tunnel-down`, `terraform-plan`, `terraform-apply`
  - `src/tripll/integrations/code_graph_rag/Makefile` — `cgr-install`, `cgr-memgraph-up`, `cgr-memgraph-down`, `cgr-export`, `cgr-doctor`, `cgr-mcp` (see [`code-graph-rag.md`](../code-graph-rag.md))
  - `dashboard/Makefile` — `dash-dev`, `dash-build`, `dash-preview`
  - `langgraph-react-agent/Makefile` — example-app targets
  - `examples/<example>/Makefile` — runnable demo targets
- **Naming.** Targets are `kebab-case`. Area-prefixed targets (`cgr-*`, `dash-*`, `infra-*`) are mandatory when the same verb appears in multiple areas (`cgr-install` vs `dash-install`); the root `install` always means "Python project install".

### Conventions

- **`.PHONY`** every non-file target. The Makefile is task-runner-shaped, not build-graph-shaped.
- **`help` target** is the default goal (`.DEFAULT_GOAL := help`) and is generated from `## ` comments after each target so descriptions live next to the target body. Standard pattern:
  ```makefile
  .DEFAULT_GOAL := help

  help: ## Show this help
  	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
  ```
- **Portability.** Targets must run under macOS (BSD `make` 3.81) and Linux (GNU `make` 4.x). Avoid GNU-only constructs unless the repo standardises on `gmake`; if so, document at the top of `Makefile` and check `MAKE_VERSION`.
- **No silent magic.** Long shell pipelines belong in `scripts/<name>.sh` (or `scripts/<name>.py`) called from a one-line target. The Makefile orchestrates; it doesn't hide complex logic.
- **Secrets.** Targets that need secrets read them from the workspace `SecretsManager` (or environment), never from arguments. `make deploy` does not take a token on the command line.
- **Variables on top.** `PYTHON ?= uv run python`, `RUFF ?= uv run ruff`, etc. — overridable by env so CI can pin if needed.

### README rule

Every README in the repo (root, per-package, examples, infra, integrations, dashboard) writes its **install / setup / run / test / deploy instructions exclusively as `make <target>` calls**. Raw `uv` / `pip` / `pytest` / `docker compose` lines do **not** appear in user-facing docs. If a target is missing, add the target — don't bypass it in the README.

This convention applies to every README created later in the project. The check is enforced socially in PR review for now; a markdown-lint custom rule (`no-bare-uv-commands-in-readme`) may be added once the surface settles.

### CI invokes `make`

GitHub Actions (and any other CI) shells out to `make <target>` rather than calling `uv run …` directly. The example pipeline in [Enforcement](#enforcement) is illustrative; the **shipping** workflow uses:

```yaml
- run: make setup
- run: make ci
```

so any drift between local and CI is caught the moment a target changes.

### When NOT to add a target

- One-off commands a developer runs once a year (an ad-hoc DB dump, a release ceremony script). Keep these in `scripts/` and invoke directly.
- Anything that genuinely needs interactive prompts inside a TTY (rare; usually the answer is to make the script non-interactive).
- Aliases for trivial single-token commands (`make ls` is silly; just type `ls`).

The bar: if a contributor or agent will type the command **more than twice**, or if it appears in any doc, it's a target.

---

## Security

- Never log or print API keys, tokens, or secrets
- File operations sandboxed to workspace path — validate all paths with `realpath`
- User input from channels goes through LLM Guard before agent processing
- Subprocess execution: always set timeout, cwd, restricted env
- No `eval()`, `exec()` on user input — use sandboxed execution tool
- Secrets stored outside workspace — resolved via `SecretsManager` pattern

**Example (workspace path containment):** *Abbreviated for this architecture document only — shipping code must still use the full module docstring (`Exports:`) and per-function docstring rules in [Comments & Documentation](#comments--documentation).*

```python
from pathlib import Path


def resolve_under_workspace(user_path: str, workspace_root: Path) -> Path:
    """Resolve user_path to an absolute path that stays under workspace_root."""
    root = workspace_root.resolve()
    candidate = (root / user_path).resolve()
    if not candidate.is_relative_to(root):
        msg = "Path escapes workspace"
        raise ValueError(msg)
    return candidate
```

---

## Tool Output Conventions

- **Large results go to disk, not context.** Any tool call that produces more than ~2 KB writes the payload to `workspace/.sevn/tool_results/<session>/<uuid>.<ext>` and returns `{path, summary, size, preview?}` instead of the raw content. The agent uses `read` / `grep` / `head` on the path when it needs the bytes. Full rationale and the threshold override policy live in `04-tools.md`.
- **Never inline secrets, tokens, or credentials in tool output** — the LLM can and will echo them. If a tool must reference a credential, reference it by alias (`{"credential_alias": "github_pat"}`), never by value.
- **Deterministic formatting.** Tool return JSON uses stable key order (sorted keys) so cache hits on prompt caching are not lost to dict iteration order.

**Example (large result handle, not raw blob in context):**

```json
{
  "path": "workspace/.sevn/tool_results/sess_abc/uuid123.json",
  "preview": "first 500 chars…",
  "size_bytes": 65536,
  "summary": "3 tables, 120 rows; see path for full export"
}
```

### Prompt cache discipline (assembled prompts)

**Normative (U17):** Every **assembled prompt segment** that participates in provider-level prefix caching must declare:

- **`cache_scope`** — logical name of the segment (`static_system`, `workspace_tools_index`, `personality_soul_user`, …).
- **`version_token`** — bumps when **any** byte of that segment’s canonical serialisation can change (tool/skill/MCP registry, `SOUL.md` hash, Triager prompt template id, etc.).

The cache layer hashes `(cache_scope, version_token, provider, model)` (exact mechanics in implementation) so Anthropic `cache_control`, OpenAI prefix caching, and Gemini Context Caching all stay correct. **Stable key order** in JSON tool returns (above) is necessary but not sufficient — segment boundaries must not shift silently.

**Cross-ref:** [`03-memory.md`](03-memory.md) compaction suffix invariant; [`04-tools.md`](04-tools.md) `registry_version` wiring.

### Single defaults module (non–workspace tunables)

**Normative (U15):** Tunables that are **not** owner-editable via `/config` / `tripll.json` live in **`src/tripll/config/defaults.py`** as typed `Final` constants with a one-line comment pointing at the architecture decision (RLM question id, doc §, or ADR). **Do not** scatter magic numbers across packages — import from `defaults` (or from a thin wrapper re-export if needed for layering).

Per-workspace surface is enumerated in [`11-onboarding.md`](11-onboarding.md) §2.

---

## Git & Commits

- **Commit messages:** [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) — enforced by the `commit-msg` pre-commit hook (`scripts/check_conventional_commit.py`). Normative guide: [`src/tripll/data/standards/conventional-commits.md`](../../src/tripll/data/standards/conventional-commits.md).
- Subject format: `<type>[(scope)][!]: <description>` with types `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`.
- Description: imperative mood, concise, no trailing period; subject line ≤ 72 characters.
- Branch naming: `feature/description`, `fix/description`, `refactor/description`
- One logical change per commit — don't mix features with refactors
- Never commit secrets, `.env` files, or API keys
- `.gitignore`: standard Python + workspace artifacts + `*.db` + `node_modules/`
- Validate before commit: `make commit-msg-check MSG='feat(gateway): short summary'`

**Examples:**

```text
# Good
feat(telegram): add webhook retry backoff
fix(gateway): stop session leak on shutdown
refactor(tools): lazy-load registry modules

# Bad
Updated stuff
WIP
fixed bug
feat: Added the voice menu.
```

---

## Config File Convention

- Workspace config: `tripll.json` (replaces the predecessor project's workspace config file)
- Config keys: `snake_case`
- Env variable prefix: `SEVN_` (replaces the predecessor project's env prefix)
- Secrets referenced as `${SECRET:source:key}` or `${ENV:VAR_NAME}` — never plaintext in config

**Example (`tripll.json` fragment):**

```json
{
  "workspace_root": ".",
  "use_code_graph_rag": true,
  "telegram": {
    "bot_token": "${ENV:SEVN_TELEGRAM_BOT_TOKEN}"
  }
}
```

---

## Enforcement

All standards are enforced automatically. Code that breaks standards **will not merge**.

> **Scope:** `scripts/check_docstrings.py` runs unconditionally against **`src/tripll/`** and **`scripts/`** (`make lint`). No per-path skip lists. The earlier staged-rollout exemptions (`_skip_secrets_package_docstrings`, `_skip_staging_agent_tools_docstrings`, `_is_still_exempt`, `_is_exempt_telegram_adapter_py`) are retired. **`tests/`** use short module docstrings only (pytest helpers are not inventoried). **`@dataclass`** synthesized `__init__` stubs are not required to duplicate the class docstring.

### Pre-commit Hook

Runs on every `git commit` locally. Blocks commit if any check fails.

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.8.0
    hooks:
      - id: ruff          # linting
        args: [--fix]
      - id: ruff-format   # formatting

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
      - id: check-toml
      - id: end-of-file-fixer
      - id: trailing-whitespace
      - id: no-commit-to-branch
        args: [--branch, main]

  - repo: local
    hooks:
      - id: docstring-check
        name: Docstring completeness check
        entry: python scripts/check_docstrings.py
        language: python
        types: [python]
        pass_filenames: true

      - id: type-hint-check
        name: Type hint check on public functions
        entry: python scripts/check_type_hints.py
        language: python
        types: [python]
        pass_filenames: true
```

### `scripts/check_docstrings.py`

Custom checker that validates:
- Every `.py` file has a module-level docstring
- Module docstring includes an `Exports:` block listing **all** public classes and public functions (optional `Private:` subsection), each with a one-line description after an em dash
- Every class has a docstring
- Every function/method (public and private) has a docstring
- Functions with parameters have an `Args:` section with `(type)` for each arg
- Functions with non-None returns have a `Returns:` section with type
- Every function/method (public and private) has an `Examples:` section with at least one `>>>` block; each command block is **syntactically** valid Python (`compile` via `scripts/check_docstrings.py`)
- Expected output and imports must match **`make doctest`** (`pytest --doctest-modules src/tripll scripts/check_docstrings.py`, same as CI `make ci`)
- Docstrings use `"""` (not `'''` or other styles)
- Docstrings with `\` use `r"""`

**Semantic** correctness of examples (matching expected output, successful imports) is enforced only by **`make doctest`** (`pytest --doctest-modules`), not by `scripts/check_docstrings.py` alone.

Exit code 1 + descriptive error message on failure.

### `scripts/check_type_hints.py`

Custom checker that validates:
- All public function parameters have type hints
- All public functions have return type hints
- Uses `|` union syntax (not `Union[]`)
- Uses lowercase generics (`list[]`, `dict[]`, not `List[]`, `Dict[]`)

### GitHub Actions CI

Runs on every push and PR. **Blocks merge** if any step fails. The shipping workflow shells out to `make <target>` (see [Makefiles & Command Surface](#makefiles--command-surface) → "CI invokes `make`") so local and CI run identical commands. The YAML below is **illustrative** — it shows the underlying tools each `make` target wraps; the real workflow is shorter and calls `make setup` then `make ci`.

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main, develop]
  pull_request:
    branches: [main, develop]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --dev
      - run: uv run ruff check src/ tests/
      - run: uv run ruff format --check src/ tests/
      - run: uv run python scripts/check_docstrings.py src/tripll scripts
      - run: uv run python scripts/check_type_hints.py src/tripll/

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --dev
      # --ignore-missing-imports relaxes strictness for third-party packages without stubs.
      # Tighten over time: add types-* packages, enable --warn-unused-ignores, then drop the flag.
      - run: uv run mypy src/tripll/ --strict --ignore-missing-imports

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --dev
      - run: uv run pytest tests/ -v --tb=short
      - run: uv run pytest --doctest-modules src/tripll/

  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --dev
      - run: uv run bandit -r src/tripll/ -c pyproject.toml
```

### Branch Protection Rules (GitHub)

- `main` branch: require PR, require all CI checks to pass, require 1 approval
- `develop` branch: require all CI checks to pass
- No force push to `main`

### Advisory quality tier (`make ci-quality`)

**Baseline + ratchet (D1):** new rule families and hygiene tools land in the **advisory** `make ci-quality` tier first. `make ci` stays green on the current tree; individual rules promote to blocking `make ci` only with operator sign-off (W6 review gate).

| Sub-target | Tool | Role |
|------------|------|------|
| `ruff-extra` | Ruff advisory families (`SLF`, `BLE`, `PTH`, …) | Per-rule ratchet via `scripts/quality/ruff_advisory_baseline.json` — counts must not increase |
| `typecheck-strict` | mypy + `pydantic.mypy` | Same strict pass as blocking `typecheck`; included so `ci-quality` is self-contained |
| `deadcode` | vulture | Whitelist-baselined (`.vulture_whitelist.py`) |
| `complexity` | xenon / radon | Thresholds tuned to current tree |
| `spell` | codespell | Domain ignore-words list |
| `deps-check` | deptry | Optional-extra false positives mapped |
| `docstring-coverage` | interrogate | `fail-under` = current % (96.8%) |

**Blocking today (promoted W1–W2):** Ruff `RET`, `RSE`, `DTZ`, `FLY`; mypy strict + `pydantic.mypy`; import-linter `Skills must not import tools` and baselined `Tools and skills must not import channels`.

**Advisory pre-commit (manual stage):** `codespell` and `vulture` hooks in `.pre-commit-config.yaml` (`stages: [manual]`) — run with `pre-commit run --hook-stage manual` when desired; they do not block ordinary commits.

**Advisory PR review:** `make review` (CodeRabbit CLI + `CODERABBIT_API_KEY`) — never referenced by `ci` or `ci-quality`.

### Additional enforcement (beyond Ruff, mypy, pytest, bandit)

Use these when you want stronger guarantees than style + types alone:

| Tool / practice | What it enforces | Typical integration |
|-----------------|------------------|---------------------|
| **`ty` or `basedpyright`** | Faster or stricter typing than mypy alone | CI job parallel to mypy, or replace mypy once stable |
| **`interrogate`** | Docstring *coverage* percentage (complements the custom checker’s structure rules) | `make docstring-coverage` / `ci-quality` (advisory) |
| **`vulture`** | Dead code / unused symbols | `make deadcode` / `ci-quality`; optional manual pre-commit |
| **`deptry` / `uv pip audit`** | Missing/unused deps, known CVEs in deps | `make deps-check` / `ci-quality` (advisory); `security` job |
| **`codespell`** | Spelling in source trees | `make spell` / `ci-quality`; optional manual pre-commit |
| **`import-linter`** | Layered import boundaries (for example `channels` must not import `tools` directly) | Blocking `make lint-imports` + advisory burn-down TODOs |
| **`semgrep`** | Org-wide security / correctness rulesets | CI on changed files |
| **Merge queue / merge bot** | Serializes merges after green checks | GitHub merge queue on `main` |
| **CODEOWNERS + required reviewers** | Human review for sensitive paths | `.github/CODEOWNERS` |

Ruff overlap: structural docstring rules stay in `scripts/check_docstrings.py` because Ruff’s `pydocstyle` port is not a drop-in for the `Exports:` / `Examples:` invariants above.

### Enforcement summary

| Check | Pre-commit (local) | CI (GitHub) | Blocks merge |
|-------|-------------------|-------------|-------------|
| Ruff lint | Yes | Yes | Yes |
| Ruff format | Yes | Yes | Yes |
| Docstring completeness | Yes | Yes | Yes |
| Type hint check | Yes | Yes | Yes |
| Docstring doctests (`doctest` / `--doctest-modules`) | Optional | Yes | Yes |
| mypy strict | No (slow) | Yes | Yes |
| pytest | No (slow) | Yes | Yes |
| bandit (security) | No | Yes | Yes |
| `make ci-quality` (advisory tier) | Manual hooks only | No | No |
| YAML/TOML validity | Yes | No | No |
| No commit to main | Yes | N/A | Yes |
