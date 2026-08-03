"""tripll.adapters — pluggable agent backends (D1).

Backends: ``claude_code`` (default), ``cursor_local``, ``cursor_cloud``,
``nous_research`` (OpenAI-compatible HTTP).

Exports:
    BACKENDS — mapping of backend name → adapter factory.
    build_adapter — construct an adapter with orchestrator-mode defaults (W4).
    build_gate_adapter — construct an adapter for headless orchestrator gate dispatch.
    get_adapter — construct an adapter by backend name.
    BackendOptions — per-dispatch model/agent overrides.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.adapters.base import AdapterCapabilities, AgentAdapter, DispatchResult
from tripll.adapters.claude_code import ClaudeCodeAdapter
from tripll.adapters.cursor_cloud import CursorCloudAdapter
from tripll.adapters.cursor_local import CursorLocalAdapter
from tripll.adapters.nous_research import NousResearchAdapter
from tripll.adapters.options import BackendOptions

if TYPE_CHECKING:
    from collections.abc import Callable

    from tripll.graph import OrchestratorConfig

__all__ = [
    "BACKENDS",
    "AdapterCapabilities",
    "AgentAdapter",
    "BackendOptions",
    "DispatchResult",
    "build_adapter",
    "build_gate_adapter",
    "get_adapter",
]

BACKENDS: dict[str, Callable[[], AgentAdapter]] = {
    "claude_code": ClaudeCodeAdapter,
    "cursor_local": CursorLocalAdapter,
    "cursor_cloud": CursorCloudAdapter,
    "nous_research": NousResearchAdapter,
}


def _resolve_orchestrator_options(
    name: str,
    opts: BackendOptions,
    orchestrator: OrchestratorConfig | None,
) -> BackendOptions:
    """Apply orchestrator-mode agent/model defaults (D9, D11).

    Args:
        name (str): Backend name (``claude_code``, ``cursor_local``, …).
        opts (BackendOptions): CLI/profile overrides.
        orchestrator (OrchestratorConfig | None): Active orchestrator config.

    Returns:
        BackendOptions: Options with orchestrator defaults applied when enabled.

    Examples:
        >>> from tripll.graph import OrchestratorConfig
        >>> from tripll.adapters.options import BackendOptions
        >>> out = _resolve_orchestrator_options(
        ...     "cursor_local", BackendOptions(), OrchestratorConfig(True, "p.md"),
        ... )
        >>> out.agent == "wave-runner"
        True
    """
    if orchestrator is None or not orchestrator.enabled:
        return opts

    agent = opts.agent or orchestrator.agent_wave
    model = opts.model

    if orchestrator.model_policy in ("inherit", "auto"):
        if model and model.startswith("composer-"):
            model = None
        elif opts.model is None:
            if name == "cursor_local":
                model = "auto" if orchestrator.model_policy == "auto" else None
            elif name == "claude_code":
                model = None

    return BackendOptions(
        model=model,
        agent=agent,
        verbose=opts.verbose,
        reasoning_effort=opts.reasoning_effort,
        max_budget_usd=opts.max_budget_usd,
    )


def build_adapter(
    name: str,
    *,
    options: BackendOptions | None = None,
    orchestrator: OrchestratorConfig | None = None,
) -> AgentAdapter:
    """Construct an adapter with optional orchestrator-mode defaults (W4.2, D11).

    When *orchestrator* is enabled:

    - Default ``agent`` to ``orchestrator.agent_wave`` (``wave-runner``).
    - Strip execution-graph ``composer-*`` model overrides.
    - For ``cursor_local`` with ``model_policy=auto``, set ``model=auto``;
      with ``inherit``, omit ``model``.

    Args:
        name (str): One of :data:`BACKENDS`.
        options (BackendOptions | None): CLI/profile overrides.
        orchestrator (OrchestratorConfig | None): Active orchestrator config.

    Returns:
        AgentAdapter: Configured adapter instance.

    Raises:
        KeyError: If *name* is not a known backend.

    Examples:
        >>> build_adapter("claude_code").name
        'claude_code'
    """
    if name not in BACKENDS:
        raise KeyError(f"Unknown backend {name!r}; choose from {sorted(BACKENDS)}")
    opts = _resolve_orchestrator_options(name, options or BackendOptions(), orchestrator)
    if name == "claude_code":
        return ClaudeCodeAdapter(
            agent=opts.agent or "wave-plan-executor",
            model=opts.model,
            verbose=opts.verbose,
            reasoning_effort=opts.reasoning_effort,
            max_budget_usd=opts.max_budget_usd,
        )
    if name == "cursor_local":
        return CursorLocalAdapter(model=opts.model, agent=opts.agent)
    if name == "nous_research":
        return NousResearchAdapter(model=opts.model)
    return BACKENDS[name]()


def build_gate_adapter(
    name: str,
    orchestrator: OrchestratorConfig,
    *,
    options: BackendOptions | None = None,
) -> AgentAdapter:
    """Build an adapter for headless ``wave-orchestrator`` gate dispatch (W4.3).

    Uses ``orchestrator.agent_orchestrator`` and applies D11 model policy for
    ``cursor_local`` only.

    Args:
        name (str): Backend name.
        orchestrator (OrchestratorConfig): Active orchestrator config.
        options (BackendOptions | None): Optional extra overrides.

    Returns:
        AgentAdapter: Gate-configured adapter.

    Examples:
        >>> from tripll.graph import OrchestratorConfig
        >>> build_gate_adapter("claude_code", OrchestratorConfig(True, "p.md")).name
        'claude_code'
    """
    base = options or BackendOptions()
    model = base.model
    if orchestrator.model_policy in ("inherit", "auto"):
        if model and model.startswith("composer-"):
            model = None
        elif base.model is None:
            if name == "cursor_local":
                model = "auto" if orchestrator.model_policy == "auto" else None
            elif name == "claude_code":
                model = None
    return build_adapter(
        name,
        options=BackendOptions(
            agent=base.agent or orchestrator.agent_orchestrator,
            model=model,
            verbose=base.verbose,
        ),
        orchestrator=None,
    )


def get_adapter(name: str, *, options: BackendOptions | None = None) -> AgentAdapter:
    """Construct an adapter by backend name.

    Args:
        name (str): One of :data:`BACKENDS`.
        options (BackendOptions | None): Optional model/agent overrides.

    Returns:
        AgentAdapter: A fresh adapter instance.

    Raises:
        KeyError: If *name* is not a known backend.

    Examples:
        >>> get_adapter("claude_code").name
        'claude_code'
    """
    return build_adapter(name, options=options)
