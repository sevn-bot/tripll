"""loguru live logging for pipeline + driver output (Wave W5, D7).

Colored loguru sink with timestamps/levels when ``--verbose/-v``,
``SKW_VERBOSE=1``, or ``skw.toml [logging].enabled`` is set. DEBUG level
includes full prompts, argv, and subprocess lines; code fences in streamed
output are pretty-printed. Clean no-op when disabled.

Exports:
    configure_logging — install/remove loguru sinks (W5).
    is_logging_active — whether a loguru sink is installed.
    is_verbose_enabled — resolve verbose gate from env + config.
    log_debug — emit a DEBUG line when logging is active.
    log_stream_line — stream one subprocess line with code-block formatting.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from loguru import logger

from tripll.skw.validate import load_skw_config

__all__: list[str] = [
    "configure_logging",
    "is_logging_active",
    "is_verbose_enabled",
    "log_debug",
    "log_stream_line",
]

_configured = False
_logging_active = False
_in_code_block = False

_LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<level>{message}</level>"
)


def is_verbose_enabled(*, verbose: bool = False, kit_root: Path | None = None) -> bool:
    """Return whether verbose logging is enabled via flag, env, or config.

    Args:
        verbose (bool): Explicit ``--verbose/-v`` flag from the CLI.
        kit_root (Path | None): Kit root for ``skw.toml`` lookup; defaults to cwd.

    Returns:
        bool: ``True`` when ``SKW_VERBOSE=1`` or ``[logging].enabled`` is set.

    Examples:
        >>> is_verbose_enabled()  # doctest: +SKIP
        False
    """
    if verbose:
        return True
    if os.environ.get("SKW_VERBOSE") == "1":
        return True
    root = kit_root or Path.cwd()
    cfg = load_skw_config(root)
    logging_cfg = cfg.get("logging", {})
    if isinstance(logging_cfg, dict):
        return bool(logging_cfg.get("enabled", False))
    return False


def is_logging_active() -> bool:
    """Return whether loguru logging is currently configured.

    Returns:
        bool: ``True`` after :func:`configure_logging` installs a sink.

    Examples:
        >>> is_logging_active()
        False
    """
    return _logging_active


def configure_logging(*, verbose: bool = False, kit_root: Path | None = None) -> bool:
    """Configure loguru when verbose logging is enabled (D7).

    Args:
        verbose (bool): Explicit verbose flag (typically from ``--verbose/-v``).
        kit_root (Path | None): Kit root for ``skw.toml`` lookup.

    Returns:
        bool: ``True`` when a colored loguru sink was installed; ``False`` when off.

    Examples:
        >>> configure_logging(verbose=False)
        False
    """
    global _configured, _logging_active, _in_code_block

    active = is_verbose_enabled(verbose=verbose, kit_root=kit_root)
    logger.remove()
    _configured = False
    _logging_active = False
    _in_code_block = False

    if not active:
        return False

    logger.add(
        sys.stderr,
        level="DEBUG",
        format=_LOG_FORMAT,
        colorize=True,
    )
    _configured = True
    _logging_active = True
    return True


def log_debug(message: str) -> None:
    """Emit a DEBUG log line when logging is active.

    Args:
        message (str): Message to log.

    Examples:
        >>> log_debug("hello")
    """
    if _logging_active:
        logger.debug(message)


def log_stream_line(line: str) -> None:
    """Stream one subprocess line with cursor-agent-like code-block formatting.

    Detects fenced `` ``` `` markers and pretty-prints block contents dimmed.

    Args:
        line (str): Raw line from agent subprocess stdout (may include newline).

    Examples:
        >>> configure_logging(verbose=True)  # doctest: +SKIP
        True
        >>> log_stream_line("```python\\n")
    """
    global _in_code_block

    if not _logging_active:
        return

    text = line.rstrip("\r\n")
    if text.startswith("```"):
        _in_code_block = not _in_code_block
        logger.opt(colors=True).debug("<cyan>{msg}</cyan>", msg=text)
        return

    if _in_code_block:
        logger.opt(colors=True).debug("<dim>{msg}</dim>", msg=text)
    else:
        logger.debug(text)
