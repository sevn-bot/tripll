"""tripll.adapters.base — AgentAdapter ABC + streaming subprocess runner.

Defines the adapter contract every backend implements (``build_argv``,
``capabilities``, async ``dispatch``) and a shared async subprocess runner that
streams combined stdout/stderr to a per-attempt log file under a wall-clock
timeout (pattern from ``sevn.tools.process``).

**Runaway guard** (W2): :func:`run_streaming` optionally enforces a ceiling on
cumulative output tokens and/or tool-use count per attempt.  Both limits are
opt-in via environment variables:

- ``TRIPLL_MAX_OUTPUT_TOKENS`` — kill the agent when cumulative output tokens
  in assistant events exceeds this value (0 / unset = disabled).
- ``TRIPLL_MAX_TOOL_USES`` — kill the agent when the tool-use block count
  in assistant events exceeds this value (0 / unset = disabled).

When triggered the function returns ``(None, captured_text, "<runaway reason>")``
so :class:`AgentAdapter.dispatch` maps it to a ``failed`` / ``timed_out``-style
outcome with evidence ``"runaway guard: <reason>"``.

Exports:
    AdapterCapabilities — backend availability + feature flags.
    DispatchResult — outcome of a single dispatch attempt.
    AgentAdapter — abstract base class for backends.
    run_streaming — async subprocess runner with log capture + timeout.
    runaway_limits_from_env — read ``TRIPLL_MAX_OUTPUT_TOKENS`` /
        ``TRIPLL_MAX_TOOL_USES`` from the environment.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

#: Type for the optional async streaming callback supplied by the engine.
#: Called with keyword arguments: ``last_action``, ``input_tokens``,
#: ``output_tokens``, ``cost_usd`` (all optional / ``None``).
StreamEventCallback = Callable[..., Awaitable[None]]

DispatchOutcome = Literal["done", "failed", "timed_out", "quota_exhausted"]

# Claude stream-json lines embed full tool payloads; default asyncio limit is 64 KiB.
_STREAM_READER_LIMIT = 16 * 1024 * 1024


def runaway_limits_from_env() -> tuple[int, int]:
    """Read runaway-guard ceilings from the environment.

    Returns:
        tuple[int, int]: ``(max_output_tokens, max_tool_uses)`` where 0 means
        disabled for that limit.

    Examples:
        >>> import os
        >>> os.environ.pop("TRIPLL_MAX_OUTPUT_TOKENS", None)
        >>> os.environ.pop("TRIPLL_MAX_TOOL_USES", None)
        >>> runaway_limits_from_env()
        (0, 0)
    """

    def _read(key: str) -> int:
        try:
            v = int(os.environ.get(key, 0))
            return max(0, v)
        except (ValueError, TypeError):
            return 0

    return _read("TRIPLL_MAX_OUTPUT_TOKENS"), _read("TRIPLL_MAX_TOOL_USES")


def _count_assistant_event(line: str) -> tuple[int, int]:
    """Extract (output_tokens_delta, tool_use_count) from one assistant stream-json line.

    Parses ``assistant`` events to accumulate output-token and tool-use counts
    for the runaway guard.  Returns ``(0, 0)`` for non-assistant lines or
    unparseable input.

    Args:
        line (str): One line of Claude ``stream-json`` output.

    Returns:
        tuple[int, int]: ``(output_tokens_delta, tool_use_count)``.

    Examples:
        >>> _count_assistant_event('{"type":"system"}')
        (0, 0)
    """
    stripped = line.strip()
    if not stripped.startswith("{"):
        return 0, 0
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return 0, 0
    if event.get("type") != "assistant":
        return 0, 0
    msg = event.get("message") or {}
    # Output tokens may appear under usage.output_tokens in each assistant chunk.
    usage = msg.get("usage") or {}
    out_tok: int = 0
    raw_out = usage.get("output_tokens")
    if isinstance(raw_out, int):
        out_tok = raw_out
    # Count tool_use blocks in content.
    tool_uses: int = 0
    for block in msg.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            tool_uses += 1
    return out_tok, tool_uses


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Backend availability and feature flags.

    Args:
        backend (str): Backend name.
        available (bool): True when the backend can run on this host.
        detail (str): Human-readable availability note.
        streaming (bool): True when the backend streams structured output.
    """

    backend: str
    available: bool
    detail: str = ""
    streaming: bool = False


@dataclass(frozen=True, slots=True)
class DispatchResult:
    """Outcome of one dispatch attempt.

    Args:
        outcome (DispatchOutcome): ``done`` | ``failed`` | ``timed_out`` | ``quota_exhausted``.
        result_text (str): Final result text (parsed or last log lines).
        returncode (int | None): Process exit code (``None`` if not run).
        log_path (str | None): Path to the attempt log file.
        argv (list[str]): The exact argv that was (or would be) executed.
        cost_usd (float | None): Provider-reported session cost when available.
        input_tokens (int | None): Input tokens when reported by the backend.
        output_tokens (int | None): Output tokens when reported by the backend.
    """

    outcome: DispatchOutcome
    result_text: str = ""
    returncode: int | None = None
    log_path: str | None = None
    argv: list[str] = field(default_factory=list)
    cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


async def run_streaming(
    argv: list[str],
    *,
    cwd: Path,
    log_path: Path,
    timeout_s: int,
    log_header: dict[str, object] | None = None,
    max_output_tokens: int = 0,
    max_tool_uses: int = 0,
    on_event: StreamEventCallback | None = None,
) -> tuple[int | None, str, str | None]:
    """Run *argv* in *cwd*, streaming combined output to *log_path*.

    Args:
        argv (list[str]): Command argv (no shell).
        cwd (Path): Working directory.
        log_path (Path): File to append combined stdout/stderr to.
        timeout_s (int): Wall-clock timeout in seconds.
        log_header (dict[str, object] | None): Optional metadata written to the log header.
        max_output_tokens (int): Runaway guard — kill the agent when cumulative
            output tokens from assistant events exceeds this value.  0 = disabled
            (default).  Controlled by ``TRIPLL_MAX_OUTPUT_TOKENS``.
        max_tool_uses (int): Runaway guard — kill the agent when cumulative
            tool-use block count from assistant events exceeds this value.
            0 = disabled (default).  Controlled by ``TRIPLL_MAX_TOOL_USES``.
        on_event (StreamEventCallback | None): Optional async callback invoked
            when a line yields an operator-relevant action or usage delta.
            Signature: ``async (*, last_action, input_tokens, output_tokens,
            cost_usd) -> None`` (all keyword, all optional / ``None``).

    Returns:
        tuple[int | None, str, str | None]: ``(returncode, captured_text, stop_reason)``.
        ``returncode`` is ``None`` when the process timed out or the runaway
        guard triggered; it was killed in both cases.
        ``stop_reason`` is set when streaming detected a quota/session cap
        (e.g. 99% utilization) *or* when the runaway guard triggered (string
        starts with ``"runaway guard:"``).

    Examples:
        >>> import asyncio
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     rc, out, qr = asyncio.run(run_streaming(
        ...         ["echo", "hi"], cwd=Path(d), log_path=Path(d) / "l.log", timeout_s=10))
        ...     rc, "hi" in out, qr
        (0, True, None)
    """
    from tripll.adapters.quota import stream_quota_pause
    from tripll.log_format import (
        format_terminal_summary,
        stamp_log_line,
        write_attempt_log_header,
    )

    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as header_fh:
        if log_header:
            attempt_raw = log_header.get("attempt", 0)
            attempt = attempt_raw if isinstance(attempt_raw, int) else 0
            write_attempt_log_header(
                header_fh,
                run_id=str(log_header.get("run_id", "")),
                node_id=str(log_header.get("node_id", "")),
                attempt=attempt,
                backend=str(log_header.get("backend", "")),
                argv=argv,
            )
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        limit=_STREAM_READER_LIMIT,
    )
    chunks: list[str] = []
    stop_reason: str | None = None
    # Runaway guard accumulators.
    cum_output_tokens: int = 0
    cum_tool_uses: int = 0
    # Live-event throttle state: only emit when action changes or token delta >= N.
    _last_action_emitted: str | None = None
    _TOKEN_DELTA_EMIT = 100  # emit on usage-delta if output tokens grew by this much
    _cum_input_tokens: int = 0
    _cum_output_tokens_emit: int = 0  # separate from runaway guard accumulator
    _cost_usd_running: float = 0.0
    with log_path.open("a", encoding="utf-8") as fh:
        assert proc.stdout is not None
        try:
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_s)
                if not line:
                    break
                text = line.decode("utf-8", errors="replace")
                fh.write(stamp_log_line(text))
                chunks.append(text)
                pause = stream_quota_pause(text)
                if pause:
                    stop_reason = pause
                    proc.kill()
                    break
                # Runaway guard: accumulate assistant-event counters.
                delta_tok, delta_tool = _count_assistant_event(text)
                cum_output_tokens += delta_tok
                cum_tool_uses += delta_tool
                if max_output_tokens > 0 and cum_output_tokens > max_output_tokens:
                    stop_reason = (
                        f"runaway guard: output tokens {cum_output_tokens} "
                        f"exceeded ceiling {max_output_tokens}"
                    )
                    proc.kill()
                    break
                if max_tool_uses > 0 and cum_tool_uses > max_tool_uses:
                    stop_reason = (
                        f"runaway guard: tool-use count {cum_tool_uses} "
                        f"exceeded ceiling {max_tool_uses}"
                    )
                    proc.kill()
                    break
                if os.environ.get("TRIPLL_DEBUG"):
                    sys.stderr.write(stamp_log_line(text))
                    sys.stderr.flush()
                elif os.environ.get("TRIPLL_VERBOSE"):
                    from tripll.adapters.stream_summary import summarize_stream_line

                    summary = summarize_stream_line(text)
                    if summary:
                        sys.stderr.write(format_terminal_summary(summary) + "\n")
                        sys.stderr.flush()
                # Live-event callback — throttled.
                if on_event is not None:
                    from tripll.adapters.stream_summary import summarize_stream_line
                    from tripll.adapters.usage import parse_stream_usage

                    action_summary = summarize_stream_line(text)
                    # Parse per-line usage delta for running cost accumulation.
                    # The result event carries final totals; assistant events carry
                    # partial output token counts.
                    _cum_output_tokens_emit += delta_tok
                    # Check for a result event carrying final cost/token totals.
                    stripped = text.strip()
                    if stripped.startswith("{"):
                        try:
                            import json as _json

                            ev = _json.loads(stripped)
                            if ev.get("type") == "result":
                                usage = parse_stream_usage(text)
                                if usage.cost_usd is not None:
                                    _cost_usd_running = usage.cost_usd
                                if usage.input_tokens is not None:
                                    _cum_input_tokens = usage.input_tokens
                                if usage.output_tokens is not None:
                                    _cum_output_tokens_emit = usage.output_tokens
                        except Exception:
                            pass
                    # Throttle: emit only when action changes or token delta >= threshold.
                    action_changed = (
                        action_summary is not None and action_summary != _last_action_emitted
                    )
                    token_delta = _cum_output_tokens_emit >= _TOKEN_DELTA_EMIT
                    if action_changed or (token_delta and _last_action_emitted is not None):
                        if action_changed:
                            _last_action_emitted = action_summary
                        await on_event(
                            last_action=_last_action_emitted,
                            input_tokens=_cum_input_tokens if _cum_input_tokens else None,
                            output_tokens=_cum_output_tokens_emit
                            if _cum_output_tokens_emit
                            else None,
                            cost_usd=_cost_usd_running if _cost_usd_running else None,
                        )
                        if token_delta:
                            _cum_output_tokens_emit = 0
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return None, "".join(chunks), None
    rc = await proc.wait()
    return rc, "".join(chunks), stop_reason


class AgentAdapter(ABC):
    """Abstract backend adapter.

    Concrete adapters implement :meth:`build_argv` and :meth:`capabilities`;
    the default :meth:`dispatch` runs the argv via :func:`run_streaming` and
    delegates result parsing to :meth:`parse_result`.

    Examples:
        >>> AgentAdapter.__name__
        'AgentAdapter'
    """

    name: str = "base"

    @abstractmethod
    def capabilities(self) -> AdapterCapabilities:
        """Return backend availability + feature flags.

        Returns:
            AdapterCapabilities: Availability and streaming flags for this backend.

        Examples:
            >>> AgentAdapter.capabilities.__name__
            'capabilities'
        """

    @abstractmethod
    def build_argv(self, brief: dict[str, object], worktree_path: Path) -> list[str]:
        """Return the exact argv to execute for *brief* in *worktree_path*.

        Args:
            brief (dict[str, object]): Dispatch brief dict.
            worktree_path (Path): Lane worktree root.

        Returns:
            list[str]: Subprocess argv (no shell).

        Examples:
            >>> AgentAdapter.build_argv.__name__
            'build_argv'
        """

    def parse_result(self, returncode: int | None, output: str) -> DispatchResult:
        """Map a process result to a :class:`DispatchResult`.

        Args:
            returncode (int | None): Process exit code (``None`` = timeout).
            output (str): Captured combined output.

        Returns:
            DispatchResult: Default mapping (``done`` iff ``returncode == 0``).

        Examples:
            >>> import inspect
            >>> inspect.isfunction(AgentAdapter.parse_result)
            True
        """
        if returncode is None:
            return DispatchResult(outcome="timed_out", result_text=output[-2000:])
        outcome: DispatchOutcome = "done" if returncode == 0 else "failed"
        return DispatchResult(outcome=outcome, result_text=output[-2000:], returncode=returncode)

    async def dispatch(
        self,
        brief: dict[str, object],
        *,
        worktree_path: Path,
        log_path: Path,
        timeout_s: int,
        log_header: dict[str, object] | None = None,
        on_event: StreamEventCallback | None = None,
    ) -> DispatchResult:
        """Dispatch *brief* and return the attempt result.

        Args:
            brief (dict[str, object]): The dispatch brief.
            worktree_path (Path): Worktree to run in.
            log_path (Path): Per-attempt log file.
            timeout_s (int): Wall-clock timeout in seconds.
            log_header (dict[str, object] | None): Optional header metadata for
                the per-attempt log file.
            on_event (StreamEventCallback | None): Optional async callback for
                live streaming events.  Called with keyword arguments
                ``last_action``, ``input_tokens``, ``output_tokens``,
                ``cost_usd`` (all optional / ``None``).  Throttled inside
                :func:`run_streaming` — not called per-line.

        Returns:
            DispatchResult: The attempt outcome.

        Examples:
            >>> import inspect
            >>> inspect.iscoroutinefunction(AgentAdapter.dispatch)
            True
        """
        import time

        from tripll.tracing.spans import trace_span

        header = log_header or {}
        run_id = str(header.get("run_id") or brief.get("run_id") or "")
        node_id = str(header.get("node_id") or brief.get("node_id") or "")
        attempt_raw = header.get("attempt")
        attempt_id = str(header.get("attempt_id") or "")
        model = str(brief.get("model") or getattr(self, "model", "") or "")
        open_attrs = {
            "backend": self.name,
            "model": model,
            "worktree": str(worktree_path),
            "timeout_s": timeout_s,
            "argv": self.build_argv(brief, worktree_path),
        }
        if attempt_raw is not None:
            open_attrs["attempt_n"] = attempt_raw

        started = time.perf_counter()
        with trace_span(
            "tripll.agent.dispatch",
            run_id=run_id or None,
            node_id=node_id or None,
            attempt_id=attempt_id or None,
            backend=self.name,
            model=model,
            worktree=str(worktree_path),
            timeout_s=timeout_s,
            argv=open_attrs["argv"],
            attempt_n=open_attrs.get("attempt_n"),
        ) as span_bag:
            caps = self.capabilities()
            argv = self.build_argv(brief, worktree_path)
            if not caps.available:
                result = DispatchResult(
                    outcome="failed",
                    result_text=f"backend {self.name!r} unavailable: {caps.detail}",
                    argv=argv,
                )
                span_bag.update(
                    outcome=result.outcome,
                    returncode=result.returncode,
                    duration_s=time.perf_counter() - started,
                    stop_reason="backend_unavailable",
                )
                return result
            max_output_tokens, max_tool_uses = runaway_limits_from_env()
            rc, output, stop_reason = await run_streaming(
                argv,
                cwd=worktree_path,
                log_path=log_path,
                timeout_s=timeout_s,
                log_header=log_header,
                max_output_tokens=max_output_tokens,
                max_tool_uses=max_tool_uses,
                on_event=on_event,
            )
            if stop_reason:
                if stop_reason.startswith("runaway guard:"):
                    result = DispatchResult(
                        outcome="failed",
                        result_text=stop_reason,
                        returncode=rc,
                        log_path=str(log_path),
                        argv=argv,
                    )
                else:
                    result = DispatchResult(
                        outcome="quota_exhausted",
                        result_text=stop_reason,
                        returncode=rc,
                        log_path=str(log_path),
                        argv=argv,
                    )
                span_bag.update(
                    outcome=result.outcome,
                    returncode=result.returncode,
                    duration_s=time.perf_counter() - started,
                    stop_reason=stop_reason,
                )
                return result
            parsed = self.parse_result(rc, output)
            result = DispatchResult(
                outcome=parsed.outcome,
                result_text=parsed.result_text,
                returncode=parsed.returncode,
                log_path=str(log_path),
                argv=argv,
                cost_usd=parsed.cost_usd,
                input_tokens=parsed.input_tokens,
                output_tokens=parsed.output_tokens,
            )
            span_bag.update(
                outcome=result.outcome,
                returncode=result.returncode,
                cost_usd=result.cost_usd,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                duration_s=time.perf_counter() - started,
                stop_reason=stop_reason,
            )
            return result
