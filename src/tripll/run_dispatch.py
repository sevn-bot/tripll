"""tripll.run_dispatch — persist and restore per-run backend/model dispatch config.

When a run starts via ``make run-set PROVIDER=… MODEL=…``, the chosen backend,
model, and agent are written to ``dispatch-config.json`` in the run directory.
Resume paths (CLI, dashboard, auto-resume after HITL) reuse that config unless
the operator passes explicit overrides.

Exports:
    DISPATCH_CONFIG_FILENAME — run-dir JSON filename.
    DispatchConfig — persisted dispatch settings.
    write_dispatch_config — write config at run start.
    read_dispatch_config — load config from a run directory.
    resolve_dispatch — merge CLI overrides with persisted values.
    resume_cli_extra_argv — build ``--backend/--model/--agent`` argv tail for resume.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for path joins
from typing import Any

DISPATCH_CONFIG_FILENAME = "dispatch-config.json"


@dataclass(frozen=True, slots=True)
class DispatchConfig:
    """Backend/model settings recorded when a run starts.

    Args:
        backend (str): Backend id (``claude_code``, ``cursor_local``, …).
        model (str | None): Provider model id (``auto``, ``claude-sonnet-4-6``, …).
        agent (str | None): Sub-agent slug when set at launch.
        role_dispatch (bool | None): Role-dispatch toggle when explicitly set.
    """

    backend: str
    model: str | None = None
    agent: str | None = None
    role_dispatch: bool | None = None


def write_dispatch_config(
    run_dir: Path,
    *,
    backend: str,
    model: str | None,
    agent: str | None,
    role_dispatch: bool | None = None,
) -> DispatchConfig:
    """Write ``dispatch-config.json`` under *run_dir*.

    Args:
        run_dir (Path): Run directory (``runs/processing/<id>/``).
        backend (str): Backend used for this run.
        model (str | None): Model override from CLI/Makefile.
        agent (str | None): Agent slug from CLI/Makefile.
        role_dispatch (bool | None): Role-dispatch toggle when set.

    Returns:
        DispatchConfig: Written configuration.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     cfg = write_dispatch_config(
        ...         Path(tmp),
        ...         backend="cursor_local",
        ...         model="auto",
        ...         agent="wave-runner",
        ...     )
        ...     cfg.backend
        'cursor_local'
    """
    cfg = DispatchConfig(
        backend=backend,
        model=model,
        agent=agent,
        role_dispatch=role_dispatch,
    )
    path = run_dir / DISPATCH_CONFIG_FILENAME
    path.write_text(json.dumps(asdict(cfg), indent=2) + "\n", encoding="utf-8")
    return cfg


def read_dispatch_config(run_dir: Path) -> DispatchConfig | None:
    """Load dispatch config when present.

    Args:
        run_dir (Path): Run directory.

    Returns:
        DispatchConfig | None: Parsed config, or ``None`` when the file is absent.

    Examples:
        >>> read_dispatch_config(Path("/nonexistent/run")) is None
        True
    """
    path = run_dir / DISPATCH_CONFIG_FILENAME
    if not path.is_file():
        return None
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return DispatchConfig(
        backend=str(raw.get("backend") or "claude_code"),
        model=raw.get("model"),
        agent=raw.get("agent"),
        role_dispatch=raw.get("role_dispatch"),
    )


def resolve_dispatch(
    run_dir: Path,
    *,
    backend: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
) -> DispatchConfig:
    """Merge explicit CLI flags with persisted run config.

    Precedence: ``provider``/``backend``/``model``/``agent`` CLI flags override
    persisted values.  When a flag is omitted, fall back to ``dispatch-config.json``,
    then to ``claude_code`` for backend only.

    Args:
        run_dir (Path): Run directory.
        backend (str | None): ``--backend`` flag (``None`` = use persisted/default).
        provider (str | None): ``--provider`` alias for backend.
        model (str | None): ``--model`` flag.
        agent (str | None): ``--agent`` flag.

    Returns:
        DispatchConfig: Effective dispatch settings.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     d = Path(tmp)
        ...     write_dispatch_config(d, backend="cursor_local", model="auto", agent=None)
        ...     resolve_dispatch(d).backend
        'cursor_local'
        ...     resolve_dispatch(d, provider="claude_code").backend
        'claude_code'
    """
    persisted = read_dispatch_config(run_dir)
    resolved_backend = provider or backend
    if resolved_backend is None:
        resolved_backend = persisted.backend if persisted else "claude_code"
    resolved_model = model if model is not None else (persisted.model if persisted else None)
    resolved_agent = agent if agent is not None else (persisted.agent if persisted else None)
    role_dispatch = persisted.role_dispatch if persisted else None
    return DispatchConfig(
        backend=resolved_backend,
        model=resolved_model,
        agent=resolved_agent,
        role_dispatch=role_dispatch,
    )


def resume_cli_extra_argv(
    run_dir: Path,
    *,
    backend: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    agent: str | None = None,
) -> list[str]:
    """Build resume argv tail with resolved backend/model/agent flags.

    Args:
        run_dir (Path): Run directory.
        backend (str | None): Optional ``--backend`` override.
        provider (str | None): Optional ``--provider`` override.
        model (str | None): Optional ``--model`` override.
        agent (str | None): Optional ``--agent`` override.

    Returns:
        list[str]: Extra CLI tokens (``--backend``, ``--model``, ``--agent``).

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.TemporaryDirectory() as tmp:
        ...     d = Path(tmp)
        ...     write_dispatch_config(d, backend="cursor_local", model="auto", agent="wave-runner")
        ...     resume_cli_extra_argv(d)
        ['--backend', 'cursor_local', '--model', 'auto', '--agent', 'wave-runner']
    """
    cfg = resolve_dispatch(
        run_dir,
        backend=backend,
        provider=provider,
        model=model,
        agent=agent,
    )
    argv: list[str] = ["--backend", cfg.backend]
    if cfg.model:
        argv.extend(["--model", cfg.model])
    if cfg.agent:
        argv.extend(["--agent", cfg.agent])
    return argv
