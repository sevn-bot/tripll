"""tripll.pipeline — folder pipeline for wave-orchestrator runs.

Input directories move through: input/ → processing/<run-id>/ → processed/ | failed/.

The *runs root* defaults to ``wave-orchestrator/runs/`` (configurable via
:class:`RunsRoot`).  ``tripll init`` creates the four top-level folders;
``claim_input`` atomically renames an input directory into ``processing/``
with a fresh run-id; ``complete_run`` and ``fail_run`` promote or demote it.

Exports:
    RunsRoot — configured runs root with folder accessors and ``init()``.
    make_run_id — derive a run-id slug from a directory name + timestamp.
    claim_input — move input dir → processing/<run-id>/ and return the run-id.
    complete_run — move processing/<run-id>/ → processed/<run-id>/.
    fail_run — move processing/<run-id>/ → failed/<run-id>/.
    list_input — list all pending entries in input/.
    list_processing — list all active run-id dirs under processing/.
    list_processed — list all completed run-id dirs under processed/.
    list_failed — list all failed run-id dirs under failed/.
    find_run_dir — locate a run directory under processing/processed/failed.
    delete_run — remove a run directory from the pipeline.
    reset_run — restore plan files to input/ and delete the run directory.
    PlanPathValidationError — raised when wave-plan in-repo refs do not resolve.
    validate_wave_plans_in_dir — validate every ``*-wave-plan.md`` under a directory.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

_RESET_INPUT_FILES = (
    "parallel-wave.md",
    "parallel-wave-review.md",
    "parallel-wave-orchestrator-prompt.md",
)
_RESET_INPUT_GLOBS = (
    "*-wave-plan.md",
    "*-wave-plan-review.md",
    "*-orchestrator-prompt.md",
)


def _is_safe_run_id(run_id: str) -> bool:
    """Return False when *run_id* could escape the runs tree via path traversal."""
    if not run_id or run_id in (".", ".."):
        return False
    if "\x00" in run_id or run_id.startswith("/"):
        return False
    if os.sep in run_id or (os.altsep and os.altsep in run_id):
        return False
    if "/" in run_id or "\\" in run_id:
        return False
    return ".." not in run_id.split("/")


def _run_dir_contained(resolved: Path, parent: Path) -> bool:
    """Return True when *resolved* is inside *parent* (SEC-02)."""
    try:
        resolved.relative_to(parent.resolve())
    except ValueError:
        return False
    return True


class PlanPathValidationError(Exception):
    """Raised when ``*-wave-plan.md`` files contain dead in-repo path refs.

    Attributes:
        errors (list[str]): Formatted ``plan → ref (try: fix)`` lines.
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("\n".join(errors))


def validate_wave_plans_in_dir(input_dir: Path, repo_root: Path) -> list[str]:
    """Validate every ``*-wave-plan.md`` under *input_dir* for dead in-repo refs.

    Args:
        input_dir (Path): Input or processing run directory.
        repo_root (Path): sevn.bot checkout used to resolve refs.

    Returns:
        list[str]: Formatted error lines (empty when all plans are valid).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> from tripll.plan_paths import validate_plan
        >>> with tempfile.TemporaryDirectory() as d:
        ...     root = Path(d)
        ...     inp = root / "set"
        ...     inp.mkdir()
        ...     plan = inp / "x-wave-plan.md"
        ...     plan.write_text("[bad](../../specs/nope.md)")
        ...     errs = validate_wave_plans_in_dir(inp, root)
        ...     len(errs) == 1
        True
    """
    from tripll.plan_paths import format_plan_ref_errors, validate_plan

    errors: list[str] = []
    for plan_path in sorted(input_dir.glob("*-wave-plan.md")):
        dead = validate_plan(plan_path, repo_root)
        if dead:
            errors.extend(format_plan_ref_errors(plan_path, dead, repo_root))
    return errors


def _chmod_and_retry_remove(func: Callable[..., Any], path: str, exc: BaseException) -> None:
    """Retry ``rmtree`` unlink/rmdir after clearing read-only bits (macOS/sqlite)."""
    if not os.path.exists(path):
        return
    try:
        os.chmod(path, stat.S_IWUSR | stat.S_IRUSR | stat.S_IXUSR)
        func(path)
    except OSError:
        raise exc from None


def _unlink_sqlite_artifacts(run_dir: Path) -> None:
    """Remove ledger sidecars before deleting the run directory."""
    for suffix in ("", "-wal", "-shm", "-journal"):
        db_path = run_dir / f"ledger.db{suffix}"
        if not db_path.is_file():
            continue
        for attempt in range(3):
            try:
                db_path.chmod(0o644)
                db_path.unlink()
                break
            except OSError as exc:
                if attempt == 2:
                    logger.warning("pipeline: could not unlink {}: {}", db_path, exc)
                else:
                    time.sleep(0.05)


def _remove_run_dir(run_dir: Path, *, repo_root: Path | None = None) -> None:
    """Delete a run directory, including git worktrees and sqlite artefacts."""
    from tripll.repo_root import resolve_repo_root
    from tripll.worktrees import cleanup_run_worktrees

    root = repo_root or resolve_repo_root()
    cleanup_run_worktrees(root, run_dir)
    _unlink_sqlite_artifacts(run_dir)
    if run_dir.exists():
        shutil.rmtree(run_dir, onexc=_chmod_and_retry_remove)
    if run_dir.exists():
        hint = ""
        if (run_dir / "ledger.db").exists():
            hint = " Stop `make serve` and close the dashboard if ledger.db is open, then retry."
        msg = f"Could not remove run directory {run_dir}.{hint}"
        raise OSError(msg)


def make_run_id(source_name: str, *, now: datetime | None = None) -> str:
    """Derive a deterministic run-id from a source directory name and a timestamp.

    The slug is the sanitised directory name (lowercase ``[a-z0-9-]``, max 32 chars).
    The timestamp is formatted ``YYYYMMDD-HHMMSS`` in UTC.

    Args:
        source_name (str): Name of the source directory (basename only).
        now (datetime | None): Override timestamp; defaults to ``datetime.now(UTC)``.

    Returns:
        str: Run-id of the form ``<slug>-<YYYYMMDD>-<HHMMSS>``.

    Examples:
        >>> make_run_id("dev_eval_14062026", now=datetime(2026, 6, 15, 16, 0, 12, tzinfo=UTC))
        'dev-eval-14062026-20260615-160012'
        >>> make_run_id("My Waves!", now=datetime(2026, 6, 15, 9, 3, 5, tzinfo=UTC))
        'my-waves-20260615-090305'
    """
    if now is None:
        now = datetime.now(UTC)
    slug = re.sub(r"[^a-z0-9]+", "-", source_name.lower()).strip("-")[:32].rstrip("-")
    ts = now.strftime("%Y%m%d-%H%M%S")
    return f"{slug}-{ts}"


class RunsRoot:
    """Configured runs root directory with folder accessors and ``init()``.

    The directory layout is::

        <root>/
            input/          ← drop a parallel-wave dir or plain wave folder here
            processing/     ← active runs (each in a <run-id>/ subdir)
            processed/      ← completed runs
            failed/         ← runs with any blocked/escalated wave

    Args:
        root (Path): Absolute or relative path to the runs root.

    Examples:
        >>> from pathlib import Path
        >>> r = RunsRoot(Path("/tmp/tripll-test/runs"))
        >>> r.input_dir
        PosixPath('/tmp/tripll-test/runs/input')
    """

    _DIRS = ("input", "processing", "processed", "failed")

    def __init__(self, root: Path) -> None:
        self.root = root

    # -- Folder accessors ---------------------------------------------------

    @property
    def input_dir(self) -> Path:
        """Return the ``input/`` directory path."""
        return self.root / "input"

    @property
    def processing_dir(self) -> Path:
        """Return the ``processing/`` directory path."""
        return self.root / "processing"

    @property
    def processed_dir(self) -> Path:
        """Return the ``processed/`` directory path."""
        return self.root / "processed"

    @property
    def failed_dir(self) -> Path:
        """Return the ``failed/`` directory path."""
        return self.root / "failed"

    # -- Lifecycle ----------------------------------------------------------

    def init(self) -> None:
        """Create the four pipeline subdirectories if they do not exist.

        Idempotent — safe to call on an already-initialised root.

        Examples:
            >>> import tempfile, os
            >>> from pathlib import Path
            >>> with tempfile.TemporaryDirectory() as d:
            ...     r = RunsRoot(Path(d) / "runs")
            ...     r.init()
            ...     sorted(os.listdir(r.root))
            ['failed', 'input', 'processed', 'processing']
        """
        for name in self._DIRS:
            path = self.root / name
            path.mkdir(parents=True, exist_ok=True)
            logger.debug("pipeline: ensured {}", path)

    def run_dir(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/`` path for an active run.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path under ``processing/``.
        """
        return self.processing_dir / run_id

    def briefs_dir(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/briefs/`` path.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path for JSON dispatch briefs.
        """
        return self.run_dir(run_id) / "briefs"

    def worktrees_dir(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/worktrees/`` path.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path for git worktree checkouts.
        """
        return self.run_dir(run_id) / "worktrees"

    def logs_dir(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/logs/`` path.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path for per-attempt log files.
        """
        return self.run_dir(run_id) / "logs"

    def traces_dir(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/traces/`` path.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path for local trace sinks (SQLite + JSONL).
        """
        return self.run_dir(run_id) / "traces"

    def ledger_path(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/ledger.db`` path.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path to the SQLite ledger database.
        """
        return self.run_dir(run_id) / "ledger.db"

    def graph_path(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/graph.json`` path.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path to the serialised RunGraph.
        """
        return self.run_dir(run_id) / "graph.json"

    def graph_db_path(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/graph.db`` path.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path to the SQLite task/code graph store.
        """
        return self.run_dir(run_id) / "graph.db"

    def checkpoints_path(self, run_id: str) -> Path:
        """Return the ``processing/<run-id>/checkpoints.db`` LangGraph path.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: Path to the derived LangGraph checkpoint store (D6).
        """
        return self.run_dir(run_id) / "checkpoints.db"

    # -- Pipeline transitions -----------------------------------------------

    def claim_input(self, source: Path, *, run_id: str | None = None) -> str:
        """Move an input directory into ``processing/<run-id>/`` atomically.

        The source must be a direct child of ``input/`` or an absolute path to
        an existing directory.  Every ``*-wave-plan.md`` is validated for dead
        in-repo markdown link refs before the move (W4 gate).

        Args:
            source (Path): Path to the input directory (must exist).
            run_id (str | None): Override run-id; otherwise derived from
                ``source.name`` + current UTC time.

        Returns:
            str: The assigned run-id.

        Raises:
            FileNotFoundError: If *source* does not exist.
            FileExistsError: If ``processing/<run-id>/`` already exists.
            PlanPathValidationError: When a wave-plan has dead in-repo refs.

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> with tempfile.TemporaryDirectory() as d:
            ...     root = RunsRoot(Path(d) / "runs")
            ...     root.init()
            ...     src = root.input_dir / "my-wave-set"
            ...     src.mkdir()
            ...     (src / "parallel-wave.md").write_text("# test")
            ...     rid = root.claim_input(src, run_id="my-wave-set-20260615-160012")
            ...     rid
            'my-wave-set-20260615-160012'
        """
        if not source.exists():
            raise FileNotFoundError(f"Input directory not found: {source}")

        from tripll.repo_root import resolve_repo_root

        root = resolve_repo_root().resolve()
        path_errors = validate_wave_plans_in_dir(source, root)
        if path_errors:
            raise PlanPathValidationError(path_errors)

        if run_id is None:
            run_id = make_run_id(source.name)

        dest = self.processing_dir / run_id
        if dest.exists():
            raise FileExistsError(f"Processing directory already exists: {dest}")

        self.processing_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
        logger.info("pipeline: claimed {} → processing/{}", source.name, run_id)
        return run_id

    def complete_run(self, run_id: str) -> Path:
        """Move ``processing/<run-id>/`` → ``processed/<run-id>/``.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: The destination path under ``processed/``.

        Raises:
            FileNotFoundError: If ``processing/<run-id>/`` does not exist.
        """
        src = self.processing_dir / run_id
        if not src.exists():
            raise FileNotFoundError(f"Processing run not found: {src}")

        self.processed_dir.mkdir(parents=True, exist_ok=True)
        dest = self.processed_dir / run_id
        shutil.move(str(src), str(dest))
        logger.info("pipeline: completed run {} → processed/", run_id)
        return dest

    def fail_run(self, run_id: str) -> Path:
        """Move ``processing/<run-id>/`` → ``failed/<run-id>/``.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: The destination path under ``failed/``.

        Raises:
            FileNotFoundError: If ``processing/<run-id>/`` does not exist.
        """
        src = self.processing_dir / run_id
        if not src.exists():
            raise FileNotFoundError(f"Processing run not found: {src}")

        self.failed_dir.mkdir(parents=True, exist_ok=True)
        dest = self.failed_dir / run_id
        shutil.move(str(src), str(dest))
        logger.info("pipeline: failed run {} → failed/", run_id)
        return dest

    def reactivate_run(self, run_id: str) -> Path:
        """Move ``failed/<run-id>/`` back to ``processing/<run-id>/`` for resume.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: The processing directory path.

        Raises:
            FileNotFoundError: If the run is not under ``failed/``.
            FileExistsError: If ``processing/<run-id>/`` already exists.
        """
        src = self.failed_dir / run_id
        if not src.exists():
            msg = f"Run {run_id!r} not found under failed/"
            raise FileNotFoundError(msg)
        dest = self.processing_dir / run_id
        if dest.exists():
            return dest
        self.processing_dir.mkdir(parents=True, exist_ok=True)
        src.rename(dest)
        logger.info("pipeline: reactivated failed run {} → processing/", run_id)
        return dest

    # -- Listing helpers ----------------------------------------------------

    def list_input(self) -> list[Path]:
        """List wave-set directories currently in ``input/``.

        Skips hidden entries (e.g. ``.DS_Store``) and non-directories.

        Returns:
            list[Path]: Sorted list of paths under ``input/``.
        """
        if not self.input_dir.exists():
            return []
        return sorted(
            p for p in self.input_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
        )

    def list_processing(self) -> list[str]:
        """List all active run-ids under ``processing/``.

        Returns:
            list[str]: Sorted run-id strings.
        """
        if not self.processing_dir.exists():
            return []
        return sorted(p.name for p in self.processing_dir.iterdir() if p.is_dir())

    def list_processed(self) -> list[str]:
        """List all completed run-ids under ``processed/``.

        Returns:
            list[str]: Sorted run-id strings.
        """
        if not self.processed_dir.exists():
            return []
        return sorted(p.name for p in self.processed_dir.iterdir() if p.is_dir())

    def list_failed(self) -> list[str]:
        """List all failed run-ids under ``failed/``.

        Returns:
            list[str]: Sorted run-id strings.
        """
        if not self.failed_dir.exists():
            return []
        return sorted(p.name for p in self.failed_dir.iterdir() if p.is_dir())

    def find_run_dir(self, run_id: str) -> Path | None:
        """Locate ``<run-id>/`` under processing, processed, or failed.

        Rejects traversal sequences, separators, and symlinks that resolve
        outside the expected parent folder (SEC-02).

        Args:
            run_id (str): Run identifier.

        Returns:
            Path | None: Run directory if found, else ``None``.
        """
        if not _is_safe_run_id(run_id):
            return None
        for folder in (self.processing_dir, self.processed_dir, self.failed_dir):
            path = folder / run_id
            if not path.is_dir():
                continue
            resolved = path.resolve()
            if not _run_dir_contained(resolved, folder):
                return None
            return path
        return None

    def delete_run(self, run_id: str) -> Path:
        """Delete a run directory from processing, processed, or failed.

        Args:
            run_id (str): Run identifier.

        Returns:
            Path: The deleted directory path.

        Raises:
            FileNotFoundError: If the run does not exist.
        """
        path = self.find_run_dir(run_id)
        if path is None:
            raise FileNotFoundError(f"Run not found: {run_id!r}")
        _remove_run_dir(path)
        logger.info("pipeline: deleted run {} ({})", run_id, path)
        return path

    def reset_run(self, run_id: str, *, input_name: str | None = None) -> Path:
        """Restore plan files to ``input/<name>/`` and delete the run directory.

        Copies wave-plan and manifest markdown from the run dir (not logs,
        ledger, worktrees, or HITL artefacts), then removes the run from
        ``processing/``, ``failed/``, or ``processed/``.

        Args:
            run_id (str): Run identifier.
            input_name (str | None): Input set folder name; defaults to ledger slug.

        Returns:
            Path: The new input set directory.

        Raises:
            FileNotFoundError: When the run or restorable plan files are missing.
            FileExistsError: When ``input/<name>/`` already exists.
        """
        from tripll.ledger import get_run, open_ledger

        run_dir = self.find_run_dir(run_id)
        if run_dir is None:
            raise FileNotFoundError(f"Run not found: {run_id!r}")

        slug = run_id.rsplit("-", 2)[0]
        ledger_path = run_dir / "ledger.db"
        if ledger_path.is_file():
            with open_ledger(ledger_path) as lc:
                slug = get_run(lc, run_id).slug

        set_name = input_name or slug
        dest = self.input_dir / set_name
        partial_retry = dest.exists() and run_dir.exists()
        if dest.exists() and not partial_retry:
            msg = f"Input set already exists: {dest} (remove it first or pick another name)"
            raise FileExistsError(msg)

        if not partial_retry:
            dest.mkdir(parents=True)
            copied = 0
            for name in _RESET_INPUT_FILES:
                src = run_dir / name
                if src.is_file():
                    shutil.copy2(src, dest / name)
                    copied += 1
            for pattern in _RESET_INPUT_GLOBS:
                for src in sorted(run_dir.glob(pattern)):
                    if src.is_file():
                        shutil.copy2(src, dest / src.name)
                        copied += 1

            if copied == 0:
                shutil.rmtree(dest)
                msg = f"No plan files to restore under {run_dir}"
                raise FileNotFoundError(msg)
        else:
            logger.info(
                "pipeline: input set {} already present — retrying run removal for {}",
                set_name,
                run_id,
            )

        _remove_run_dir(run_dir)
        logger.info("pipeline: reset run {} → input/{} (removed {})", run_id, set_name, run_dir)
        return dest
