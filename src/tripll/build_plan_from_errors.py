"""tripll.build_plan_from_errors — turn-bundle folder → wave-plan driver (W5).

Reads per-day ``<folder>/<DDMMYY>/index.json`` (and legacy flat ``<folder>/index.json``),
selects unprocessed turns across all day partitions, evaluates each bundle's
``has_error`` predicate, flips ``processed`` to ``true`` for all evaluated turns,
and when the run finds at least one error dispatches the W4 agent+prompt to emit
a single tripll v1 ``*-wave-plan.md`` into:

``wave-orchestrator/runs/input/from-errors-<run_id>/``

Exports:
    DEFAULT_TURN_BUNDLES_FOLDER — default ``<content_root>/.sevn/turns`` relative hint.
    print_usage — operator usage text.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Final, TextIO, TypedDict, cast

from loguru import logger

from tripll.adapters import BackendOptions, get_adapter
from tripll.pipeline import make_run_id
from tripll.repo_root import resolve_repo_root

_DEFAULT_TIMEOUT_S: Final[int] = 1800
DEFAULT_TURN_BUNDLES_FOLDER: Final[str] = ".sevn/turns"
_RUN_ID_SOURCE_NAME: Final[str] = "turn-bundle-build-plan"

_PROMPT_AGENT_DEF_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "agents" / "build-plan-from-errors.md"
)
_PROMPT_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2] / "docs" / "prompts" / "build-plan-from-errors.md"
)
_PROBLEM_TYPES_TEMPLATE_PATH = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "prompts"
    / "build-plan-from-errors-problem-types.md"
)

_TURN_BUNDLE_INDEX_VERSION: Final[int] = 1

# D5 — error predicate (mirrors ``sevn.gateway.turn_bundle.compute_has_error``).
_TURN_TERMINAL_FAILURE_STATUSES: Final[frozenset[str]] = frozenset({"error"})
_TRACE_ERROR_STATUSES: Final[frozenset[str]] = frozenset(
    {"error", "failed", "denied", "cancelled", "escalated"}
)
_ERROR_LOG_LEVELS: Final[frozenset[str]] = frozenset({"ERROR", "CRITICAL"})
_ERROR_LOG_SUBSTRINGS: Final[tuple[str, ...]] = ("executor_no_answer",)


class TurnBundleIndexEntry(TypedDict):
    """One element of ``index.json`` ``turns[]`` (D4)."""

    turn_id: str
    file: str
    session_id: str
    channel: str
    terminal_status: str
    has_error: bool
    processed: bool


class TurnBundleIndex(TypedDict):
    """Top-level ``index.json`` document (D4)."""

    version: int
    turns: list[TurnBundleIndexEntry]


def _log_line_indicates_error(line: str) -> bool:
    if any(marker in line for marker in _ERROR_LOG_SUBSTRINGS):
        return True
    return any(f"| {level}" in line or f"| {level:<8}" in line for level in _ERROR_LOG_LEVELS)


def _compute_has_error(
    *,
    terminal_status: str,
    trace_statuses: list[str] | tuple[str, ...] | None,
    log_lines: list[str] | tuple[str, ...] | None,
) -> bool:
    if terminal_status in _TURN_TERMINAL_FAILURE_STATUSES:
        return True
    for status in trace_statuses or ():
        if status in _TRACE_ERROR_STATUSES:
            return True
    return any(_log_line_indicates_error(line) for line in log_lines or ())


def _load_turn_bundle_records(bundle_path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with bundle_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(cast("dict[str, object]", json.loads(line)))
    return records


def _load_turn_bundle_index(index_path: Path) -> TurnBundleIndex:
    if not index_path.is_file():
        return {"version": _TURN_BUNDLE_INDEX_VERSION, "turns": []}
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    # Keep this loader intentionally permissive; tests and the write path keep schema consistent.
    turns = cast("list[dict[str, object]]", payload.get("turns", []))
    typed_turns: list[TurnBundleIndexEntry] = [cast("TurnBundleIndexEntry", t) for t in turns]
    return {
        "version": _TURN_BUNDLE_INDEX_VERSION,
        "turns": typed_turns,
    }


def _is_turn_bundle_day_slug(name: str) -> bool:
    """Return whether ``name`` is a day-partition folder slug (``DDMMYY``)."""
    return len(name) == 6 and name.isdigit()


def _iter_turn_bundle_storage_dirs(turns_root: Path) -> list[Path]:
    """Return day partition dirs and legacy flat ``turns/`` when indexed."""
    dirs: list[Path] = []
    if not turns_root.is_dir():
        return dirs
    for child in sorted(turns_root.iterdir()):
        if child.is_dir() and _is_turn_bundle_day_slug(child.name):
            dirs.append(child)
    legacy_index = turns_root / "index.json"
    if (legacy_index.is_file() or any(turns_root.glob("*.jsonl"))) and turns_root not in dirs:
        dirs.append(turns_root)
    return dirs


def print_usage(*, stream: TextIO = sys.stderr) -> None:
    """Print ``build-plan-from-errors`` usage.

    Args:
        stream (object): Writable stream (defaults to ``sys.stderr``).

    Examples:
        >>> import io
        >>> buf = io.StringIO()
        >>> print_usage(stream=buf)
        >>> "build-plan-from-errors" in buf.getvalue()
        True
    """
    text = f"""build-plan-from-errors — emit tripll v1 plans from turn-bundle errors

Usage:
  make build-plan-from-errors FOLDER=<dir> [PROVIDER=…] [MODEL=…] [AGENT=…]
  make build-plan-from-errors --folder=<dir>   # GNU make pseudo-goal

CLI:
  python -m tripll.build_plan_from_errors --folder=<dir> [--backend=…] [--model=…] [--agent=…]
  python -m tripll.build_plan_from_errors --dry-run --folder=<dir>

  --folder defaults to <content_root>/{DEFAULT_TURN_BUNDLES_FOLDER}
"""
    stream.write(text)
    stream.flush()


def _find_content_root_for_bundles_dir(*, bundles_dir: Path, fallback_repo_root: Path) -> Path:
    """Find the sevn workspace root containing ``sevn.json``.

    Args:
        bundles_dir (Path): Absolute turn-bundles directory.
        fallback_repo_root (Path): Used when no ``sevn.json`` is found.

    Returns:
        Path: Content root containing ``sevn.json`` (or ``fallback_repo_root``).
    """
    for p in (bundles_dir, *bundles_dir.parents):
        if (p / "sevn.json").is_file():
            return p
    return fallback_repo_root


def _atomic_write_bytes(final_path: Path, payload: bytes) -> None:
    """Write bytes via temp file + ``os.replace``.

    Args:
        final_path (Path): Destination path.
        payload (bytes): File body.
    """
    final_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=final_path.parent,
        prefix=f".{final_path.name}-",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
        os.replace(tmp_name, final_path)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise


def _write_index(index_path: Path, index: TurnBundleIndex) -> None:
    """Write ``index.json`` atomically."""
    payload = (json.dumps(index, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _atomic_write_bytes(index_path, payload)


def _evaluate_bundle_has_error(*, bundle_path: Path) -> bool:
    """Evaluate one turn bundle's error predicate.

    Args:
        bundle_path (Path): ``*.jsonl`` bundle file path.

    Returns:
        bool: Whether the bundle should be treated as having errors.
    """
    records = _load_turn_bundle_records(bundle_path)
    meta = records[0]
    terminal_status = cast("str", meta["terminal_status"])
    trace_statuses: list[str] = [
        cast("str", r["status"]) for r in records if cast("str", r["stream"]) == "trace"
    ]
    log_lines: list[str] = [
        cast("str", r["message"]) for r in records if cast("str", r["stream"]) == "log"
    ]
    return _compute_has_error(
        terminal_status=terminal_status,
        trace_statuses=trace_statuses,
        log_lines=log_lines,
    )


def _resolved_prompt_text(
    *,
    run_id: str,
    bundles_dir: Path,
    content_root: Path,
    error_turn_ids: list[str],
    output_dir: Path,
) -> str:
    """Build the prompt string by substituting placeholders in the W4 template.

    Appends the turn-problem taxonomy template so every dispatch includes the
    per-turn checklist the agent must fill before authoring waves.
    """
    agent_def_text = _PROMPT_AGENT_DEF_PATH.read_text(encoding="utf-8")
    template = _PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    problem_types_text = _PROBLEM_TYPES_TEMPLATE_PATH.read_text(encoding="utf-8")
    error_turn_ids_cell = ", ".join(error_turn_ids)
    mapping = {
        "{{RUN_ID}}": run_id,
        "{{BUNDLES_FOLDER}}": str(bundles_dir),
        "{{CONTENT_ROOT}}": str(content_root),
        "{{ERROR_TURN_IDS}}": error_turn_ids_cell,
        "{{OUTPUT_DIR}}": str(output_dir),
    }
    resolved = template
    for k, v in mapping.items():
        resolved = resolved.replace(k, v)
        problem_types_text = problem_types_text.replace(k, v)
    return agent_def_text + "\n\n---\n\n" + resolved + "\n\n---\n\n" + problem_types_text


async def _dispatch_once(
    *,
    backend: str,
    model: str | None,
    agent: str | None,
    dry_run: bool,
    worktree_path: Path,
    brief_prompt: str,
    output_dir: Path,
    timeout_s: int,
) -> int:
    """Dispatch the configured backend once (or print argv in dry-run)."""
    adapter = get_adapter(
        backend,
        options=BackendOptions(model=model, agent=agent, verbose=False),
    )

    if not adapter.capabilities().available:
        logger.error("Backend unavailable: {}", adapter.capabilities().detail)
        return 1

    owned_paths: list[str] = []
    try:
        rel = output_dir.relative_to(worktree_path)
        owned_paths = [rel.as_posix()]
    except ValueError:
        owned_paths = []

    brief: dict[str, object] = {
        "wave_id": "W5",
        "plan_worktree_path": brief_prompt,
        "branch": "build-plan-from-errors",
        "worktree_path": str(worktree_path),
        "owned_paths": owned_paths,
        "forbidden_paths": [],
        "verify_targets": [],
        "prerequisite_waves": [],
        "locked_decisions": [],
        "manual_smoke_deferred": [],
        "agent_directives": [],
        "node_id": "build-plan-from-errors:dispatch",
        "plan_file": "build-plan-from-errors",
        "workspace_scope": owned_paths,
        "model": model or "",
        "output_dir": str(output_dir),
    }

    argv = adapter.build_argv(brief, worktree_path)
    if dry_run:
        # Make it readable for humans + grep-based tests.
        out = "[dry-run argv] " + " ".join(repr(a) if (" " in a or "\n" in a) else a for a in argv)
        sys.stdout.write(out + "\n")
        sys.stdout.flush()
        return 0

    log_path = output_dir / "dispatch.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    result = await adapter.dispatch(
        brief,
        worktree_path=worktree_path,
        log_path=log_path,
        timeout_s=timeout_s,
        log_header={"run_id": output_dir.name, "node_id": brief["node_id"], "backend": backend},
    )
    if result.outcome != "done":
        logger.error("dispatch failed: {} {}", result.outcome, result.result_text[:300])
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for ``make build-plan-from-errors``.

    Args:
        argv (list[str] | None): Optional argv override (tests). When ``None``, uses
            ``sys.argv[1:]``.

    Returns:
        int: Process exit code (``0`` success, ``1`` dispatch failure, ``2`` usage).

    Examples:
        >>> main([]) == 2
        True
    """
    if argv is None:
        argv = sys.argv[1:]
    if not argv:
        print_usage()
        return 2

    parser = argparse.ArgumentParser(
        prog="build-plan-from-errors",
        add_help=True,
    )
    parser.add_argument(
        "--folder",
        default=DEFAULT_TURN_BUNDLES_FOLDER,
        help=f"Turn-bundles directory (default: <content_root>/{DEFAULT_TURN_BUNDLES_FOLDER})",
    )
    parser.add_argument("--backend", "--provider", dest="backend", default="claude_code")
    parser.add_argument("--model", default=None)
    parser.add_argument("--agent", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-s", type=int, default=_DEFAULT_TIMEOUT_S)
    ns = parser.parse_args(argv)

    repo_root = resolve_repo_root()
    bundles_dir_raw = Path(ns.folder)
    bundles_dir = (
        bundles_dir_raw if bundles_dir_raw.is_absolute() else (repo_root / bundles_dir_raw)
    ).resolve()
    content_root = _find_content_root_for_bundles_dir(
        bundles_dir=bundles_dir, fallback_repo_root=repo_root
    )

    storage_dirs = _iter_turn_bundle_storage_dirs(bundles_dir)
    if not storage_dirs:
        return 0

    error_turn_ids: list[str] = []
    for storage_dir in storage_dirs:
        index_path = storage_dir / "index.json"
        index = _load_turn_bundle_index(index_path)
        candidates = [t for t in index["turns"] if not t.get("processed", False)]
        if not candidates:
            continue

        for entry in list(candidates):
            turn_id = entry["turn_id"]
            bundle_path = storage_dir / entry["file"]
            try:
                has_error = _evaluate_bundle_has_error(bundle_path=bundle_path)
            except Exception as exc:  # pragma: no cover (best-effort fallback)
                logger.warning("bundle evaluate failed for {}: {}", turn_id, exc)
                has_error = bool(entry.get("has_error", False))

            if has_error:
                error_turn_ids.append(turn_id)

            if not ns.dry_run:
                for idx_entry in index["turns"]:
                    if idx_entry["turn_id"] != turn_id:
                        continue
                    idx_entry["has_error"] = has_error
                    idx_entry["processed"] = True
                    break
                _write_index(index_path, index)

    if not error_turn_ids:
        return 0

    run_id = make_run_id(_RUN_ID_SOURCE_NAME)
    tripll_root = Path(__file__).resolve().parents[2]
    output_dir = tripll_root / "runs" / "input" / f"from-errors-{run_id}"

    prompt_text = _resolved_prompt_text(
        run_id=run_id,
        bundles_dir=bundles_dir,
        content_root=content_root,
        error_turn_ids=error_turn_ids,
        output_dir=output_dir,
    )
    if ns.dry_run:
        return asyncio.run(
            _dispatch_once(
                backend=ns.backend,
                model=ns.model,
                agent=ns.agent,
                dry_run=True,
                worktree_path=content_root,
                brief_prompt=prompt_text,
                output_dir=output_dir,
                timeout_s=ns.timeout_s,
            )
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    return asyncio.run(
        _dispatch_once(
            backend=ns.backend,
            model=ns.model,
            agent=ns.agent,
            dry_run=False,
            worktree_path=content_root,
            brief_prompt=prompt_text,
            output_dir=output_dir,
            timeout_s=ns.timeout_s,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
