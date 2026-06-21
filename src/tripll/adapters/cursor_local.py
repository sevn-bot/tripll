"""tripll.adapters.cursor_local — Cursor agent CLI backend (local headless).

Drives the local ``agent`` (or legacy ``cursor-agent``) binary behind a
capability gate. When the binary is absent the adapter reports unavailable
with a clear message and never attempts to exec (D1).

Exports:
    CursorLocalAdapter — local Cursor CLI adapter.
    resolve_cursor_cli — return the first available Cursor CLI binary name.
"""

from __future__ import annotations

import json
import shutil
from typing import TYPE_CHECKING

from tripll.adapters.base import (
    AdapterCapabilities,
    AgentAdapter,
    DispatchOutcome,
    DispatchResult,
)
from tripll.adapters.quota import is_quota_exhausted
from tripll.adapters.usage import parse_stream_usage
from tripll.brief import render_dispatch_prompt

if TYPE_CHECKING:
    from pathlib import Path


def resolve_cursor_cli() -> str | None:
    """Return ``agent`` or ``cursor-agent`` when on PATH, else None.

    Returns:
        str | None: Binary name when found.

    Examples:
        >>> isinstance(resolve_cursor_cli(), (str, None))
        True
    """
    for name in ("agent", "cursor-agent"):
        if shutil.which(name):
            return name
    return None


class CursorLocalAdapter(AgentAdapter):
    """Local Cursor CLI headless adapter (capability-gated).

    Args:
        model (str | None): ``--model`` value (e.g. ``auto``, ``composer-2.5``).
        agent (str | None): ``--agent`` subagent slug (e.g. ``wave-runner``).
    """

    name = "cursor_local"

    def __init__(self, *, model: str | None = None, agent: str | None = None) -> None:
        """See class docstring for parameter semantics.

        Examples:
            >>> CursorLocalAdapter(model="auto").model
            'auto'
        """
        self.model = model
        self.agent = agent

    def capabilities(self) -> AdapterCapabilities:
        """Return availability based on ``agent`` / ``cursor-agent`` on PATH.

        Returns:
            AdapterCapabilities: ``available`` when a Cursor CLI binary exists.

        Examples:
            >>> isinstance(CursorLocalAdapter().capabilities().available, bool)
            True
        """
        cli = resolve_cursor_cli()
        found = cli is not None
        return AdapterCapabilities(
            backend=self.name,
            available=found,
            detail=(
                f"{cli} found"
                if found
                else "Cursor CLI not installed — install `agent` to use this backend"
            ),
            streaming=found,
        )

    def build_argv(self, brief: dict[str, object], worktree_path: Path) -> list[str]:
        """Return the Cursor CLI argv for *brief* in *worktree_path*.

        The ``agent`` binary supports ``--workspace`` (primary project root) but
        not Claude's ``--add-dir`` or ``--agent`` subagent flag.  Scoped paths
        from ``workspace_scope`` must live under the worktree; subagent slugs
        are conveyed in the prompt text instead.

        Args:
            brief (dict[str, object]): Dispatch brief from :func:`render_json_brief`.
            worktree_path (Path): Lane worktree to run in.

        Returns:
            list[str]: ``agent --print --output-format stream-json …`` argv.

        Examples:
            >>> from pathlib import Path
            >>> argv = CursorLocalAdapter(model="auto").build_argv(
            ...     {"workspace_scope": [], "agent_directives": []},
            ...     Path("/wt"),
            ... )
            >>> "--workspace" in argv and "--verbose" in argv
            True
        """
        cli = resolve_cursor_cli() or "agent"
        override = brief.get("_prompt_override")
        prompt = str(override) if override else render_dispatch_prompt(brief)
        agent = str(brief.get("agent") or "").strip() or self.agent
        if agent:
            prompt = f"Use the {agent} subagent workflow.\n\n{prompt}"
        argv = [
            cli,
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--workspace",
            str(worktree_path.resolve()),
            "--trust",
        ]
        model = str(brief.get("model") or "").strip() or self.model
        if model:
            argv += ["--model", model]
        argv.append(prompt)
        return argv

    def parse_result(self, returncode: int | None, output: str) -> DispatchResult:
        """Parse stream-json or text output for the final result.

        Args:
            returncode (int | None): Process exit code (``None`` on timeout).
            output (str): Combined stream-json stdout.

        Returns:
            DispatchResult: Parsed outcome with usage when present.

        Examples:
            >>> r = CursorLocalAdapter().parse_result(
            ...     0, '{"type":"result","result":"done","is_error":false}'
            ... )
            >>> r.outcome == "done"
            True
        """
        if returncode is None:
            return DispatchResult(outcome="timed_out", result_text=output[-2000:])
        result_text = ""
        is_error = False
        for line in output.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "result":
                result_text = str(event.get("result", ""))
                is_error = bool(event.get("is_error", False))
        text = result_text or output[-2000:]
        usage = parse_stream_usage(output)
        if is_quota_exhausted(text):
            return DispatchResult(
                outcome="quota_exhausted",
                result_text=text,
                returncode=returncode,
                cost_usd=usage.cost_usd,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        outcome: DispatchOutcome = "done" if returncode == 0 and not is_error else "failed"
        return DispatchResult(
            outcome=outcome,
            result_text=text,
            returncode=returncode,
            cost_usd=usage.cost_usd,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )
