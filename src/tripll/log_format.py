"""tripll.log_format — timestamps and headers for attempt logs + terminal summaries.

Exports:
    log_timestamp — current local timestamp string.
    stamp_log_line — prefix one log line with a timestamp.
    write_attempt_log_header — banner at the start of each attempt log file.
    format_terminal_summary — timestamped one-liner for operator stderr.
"""

from __future__ import annotations

import shlex
from datetime import datetime
from typing import IO


def log_timestamp() -> str:
    """Return a local-system timestamp for log lines.

    Returns:
        str: ``YYYY-MM-DD HH:MM:SS`` in the host local timezone.

    Examples:
        >>> len(log_timestamp()) >= 19
        True
    """
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")


def stamp_log_line(line: str) -> str:
    """Prefix *line* with a local timestamp when it is non-empty.

    Args:
        line (str): Raw line (may include trailing newline).

    Returns:
        str: Timestamped line (preserves trailing newline when present).

    Examples:
        >>> stamp_log_line('hello\\n').startswith('[')
        True
    """
    if not line.strip():
        return line
    ts = log_timestamp()
    if line.lstrip().startswith(f"[{ts[:10]}"):
        return line
    nl = "\n" if line.endswith("\n") else ""
    body = line.rstrip("\n")
    return f"[{ts}] {body}{nl}"


def write_attempt_log_header(
    fh: IO[str],
    *,
    run_id: str,
    node_id: str,
    attempt: int,
    backend: str,
    argv: list[str],
) -> None:
    """Write a structured header at the top of an attempt log file.

    Args:
        fh (IO[str]): Open log file handle (append mode).
        run_id (str): Run identifier.
        node_id (str): Wave node id.
        attempt (int): 1-based attempt number.
        backend (str): Adapter backend name.
        argv (list[str]): Command argv for this dispatch.
    """
    ts = log_timestamp()
    fh.write(f"\n{'=' * 72}\n")
    fh.write(f"[{ts}] ATTEMPT START\n")
    fh.write(f"[{ts}] run_id={run_id}\n")
    fh.write(f"[{ts}] node_id={node_id}\n")
    fh.write(f"[{ts}] attempt={attempt}\n")
    fh.write(f"[{ts}] backend={backend}\n")
    try:
        cmd = shlex.join(argv)
    except (TypeError, ValueError):
        cmd = " ".join(str(a) for a in argv)
    fh.write(f"[{ts}] command={cmd}\n")
    fh.write(f"{'=' * 72}\n")


def format_terminal_summary(summary: str) -> str:
    """Return *summary* with a local timestamp prefix for stderr display.

    Args:
        summary (str): One-line operator summary (may include leading spaces).

    Returns:
        str: Timestamped summary line without trailing newline.

    Examples:
        >>> format_terminal_summary("  ✓ agent finished").startswith("[")
        True
    """
    stripped = summary.strip()
    return f"[{log_timestamp()}] {stripped}"
