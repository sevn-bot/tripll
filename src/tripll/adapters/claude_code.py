"""tripll.adapters.claude_code — Claude Code CLI backend (default).

Builds a headless ``claude -p`` invocation that runs the wave-plan-executor
agent against a worktree and parses the ``stream-json`` output for the final
result. This is the default backend (D1); the binary must be on ``PATH``.

Default model is ``claude-sonnet-4-6`` (see :data:`DEFAULT_MODEL`).  Opus is
used **only** when the wave's execution-graph row explicitly declares a model
override — no wave silently escalates to a higher-cost model.

Exports:
    DEFAULT_MODEL — the string used when no per-wave model override is set.
    resolve_add_dir — map one workspace_scope entry to a --add-dir directory.
    collect_add_dirs — deduplicated --add-dir paths for a scope list.
    ClaudeCodeAdapter — the default Claude Code CLI adapter.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from tripll.adapters.base import (
    AdapterCapabilities,
    AgentAdapter,
    DispatchOutcome,
    DispatchResult,
)
from tripll.adapters.quota import is_quota_exhausted
from tripll.adapters.usage import parse_stream_usage
from tripll.brief import _brief_str_list, render_dispatch_prompt

#: Default model for every wave dispatch.  Opus is never used implicitly;
#: the wave's execution-graph row must declare ``model: claude-opus-…``
#: explicitly to override this.
DEFAULT_MODEL = "claude-sonnet-4-6"


def resolve_add_dir(worktree_path: Path, rel: str) -> Path:
    """Map one ``workspace_scope`` entry to a directory for ``claude --add-dir``.

    Claude's ``--add-dir`` accepts directories only.  File paths, globs, and
    toolchain entries (``Makefile``, ``pyproject.toml``) map to their parent
    directory under *worktree_path*.  Absolute paths outside the worktree
    (external uploads) pass through unchanged (D3).

    Args:
        worktree_path (Path): Lane worktree root.
        rel (str): One ``workspace_scope`` entry (relative or absolute).

    Returns:
        Path: Directory to pass to ``--add-dir``.

    Examples:
        >>> from pathlib import Path
        >>> resolve_add_dir(Path("/wt"), "specs/18.md").as_posix().endswith("specs")
        True
        >>> resolve_add_dir(Path("/wt"), "").as_posix().endswith("/wt")
        True
    """
    raw = rel.strip()
    if not raw:
        return worktree_path
    candidate = Path(raw).expanduser()
    if candidate.is_absolute():
        if candidate.is_file():
            return candidate.parent
        if candidate.is_dir():
            return candidate
        if "." in candidate.name:
            return candidate.parent
        return candidate
    raw = raw.lstrip("/").rstrip("/")
    if raw.endswith("/*"):
        raw = raw[:-2]
    if "*" in raw:
        raw = raw.rsplit("/", 1)[0] if "/" in raw else "."
    candidate = worktree_path if raw == "." else worktree_path / raw
    if candidate.is_file():
        return candidate.parent
    if candidate.is_dir():
        return candidate
    if "." in candidate.name:
        return candidate.parent
    return candidate


def collect_add_dirs(worktree_path: Path, scope: list[str]) -> list[Path]:
    """Return deduplicated directory paths for ``--add-dir`` flags.

    Args:
        worktree_path (Path): Lane worktree root.
        scope (list[str]): ``workspace_scope`` entries from the brief.

    Returns:
        list[Path]: Unique directories (defaults to worktree when *scope* is empty).

    Examples:
        >>> from pathlib import Path
        >>> dirs = collect_add_dirs(Path("/wt"), ["src/a.py", "src/a/b.py"])
        >>> len(dirs) == 1 and dirs[0].as_posix().endswith("src/a")
        True
    """
    seen: set[str] = set()
    out: list[Path] = []
    for rel in scope:
        directory = resolve_add_dir(worktree_path, rel)
        key = str(directory.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(directory)
    return out or [worktree_path]


class ClaudeCodeAdapter(AgentAdapter):
    """Claude Code CLI adapter (``claude -p --output-format stream-json``).

    The default model is :data:`DEFAULT_MODEL` (``claude-sonnet-4-6``).  A
    per-wave model override from the execution-graph row takes precedence when
    set; when absent the default applies so no wave silently runs on a
    higher-cost model.

    ``build_argv`` always passes ``--verbose`` with ``-p --output-format
    stream-json`` (required by the Claude CLI).

    Args:
        agent (str): Sub-agent name to invoke (default ``wave-plan-executor``).
        permission_mode (str): ``claude --permission-mode`` value.
        skip_permissions (bool): When True, pass
            ``--dangerously-skip-permissions`` instead of ``--permission-mode``.
        model (str | None): Adapter-level default model override.  Falls back
            to :data:`DEFAULT_MODEL` (``claude-sonnet-4-6``) when ``None``.
        verbose (bool): Retained for API compatibility; ``--verbose`` is always
            emitted for the ``stream-json`` headless invocation.

    Examples:
        >>> ClaudeCodeAdapter().name
        'claude_code'
        >>> ClaudeCodeAdapter().model is None  # resolved at build_argv time
        True
    """

    name = "claude_code"

    def __init__(
        self,
        *,
        agent: str = "wave-plan-executor",
        permission_mode: str = "acceptEdits",
        skip_permissions: bool = False,
        model: str | None = None,
        verbose: bool = False,
    ) -> None:
        """See class docstring for parameter semantics."""
        self.agent = agent
        self.permission_mode = permission_mode
        self.skip_permissions = skip_permissions
        self.model = model
        self.verbose = verbose

    def capabilities(self) -> AdapterCapabilities:
        """Return availability based on the presence of the ``claude`` binary.

        Returns:
            AdapterCapabilities: ``available`` when ``claude`` is on ``PATH``.

        Examples:
            >>> isinstance(ClaudeCodeAdapter().capabilities().available, bool)
            True
        """
        found = shutil.which("claude") is not None
        return AdapterCapabilities(
            backend=self.name,
            available=found,
            detail="claude CLI found" if found else "claude CLI not on PATH",
            streaming=True,
        )

    def _add_dirs(self, argv: list[str], brief: dict[str, object], worktree_path: Path) -> None:
        """Append ``--add-dir`` flags derived from ``workspace_scope`` in *brief*."""
        scope = _brief_str_list(brief, "workspace_scope")
        for directory in collect_add_dirs(worktree_path, scope):
            argv.extend(["--add-dir", str(directory.resolve())])

    def build_argv(self, brief: dict[str, object], worktree_path: Path) -> list[str]:
        """Return the exact ``claude`` argv for *brief* in *worktree_path*.

        Args:
            brief (dict[str, object]): Dispatch brief from :func:`render_json_brief`.
            worktree_path (Path): Lane worktree to run in.

        Returns:
            list[str]: ``claude -p --output-format stream-json …`` argv.

        Examples:
            >>> from pathlib import Path
            >>> argv = ClaudeCodeAdapter().build_argv(
            ...     {"workspace_scope": [], "agent_directives": []},
            ...     Path("/wt"),
            ... )
            >>> argv[0] == "claude" and "--verbose" in argv
            True
        """
        prompt = render_dispatch_prompt(brief)
        agent = str(brief.get("agent") or "").strip() or self.agent
        argv = [
            "claude",
            "-p",
            "--output-format",
            "stream-json",
            "--agent",
            agent,
            "--verbose",
        ]
        self._add_dirs(argv, brief, worktree_path)
        if self.skip_permissions:
            argv.append("--dangerously-skip-permissions")
        else:
            argv += ["--permission-mode", self.permission_mode]
        # Resolve model: per-wave override → adapter-level default → DEFAULT_MODEL.
        # Opus is never used implicitly — the wave must declare it explicitly.
        model = str(brief.get("model") or "").strip() or self.model or DEFAULT_MODEL
        argv += ["--model", model]
        argv.append(prompt)
        return argv

    def parse_result(self, returncode: int | None, output: str) -> DispatchResult:
        """Parse ``stream-json`` output for the final ``result`` event.

        Args:
            returncode (int | None): Process exit code (``None`` on timeout).
            output (str): Combined stream-json stdout.

        Returns:
            DispatchResult: Parsed outcome with usage when present.

        Examples:
            >>> r = ClaudeCodeAdapter().parse_result(
            ...     0, '{"type":"result","result":"ok","is_error":false}'
            ... )
            >>> r.outcome == "done" and r.result_text == "ok"
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
        usage = parse_stream_usage(output)
        text = result_text or output[-2000:]
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
