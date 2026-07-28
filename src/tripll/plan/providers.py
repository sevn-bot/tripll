"""Parse v3 plan provider + pipeline dispatch config.

Exports:
    VALID_REASONING_EFFORT — allowed ``reasoning_effort`` values (EFFORT-01).
    validate_reasoning_effort — reject invalid effort at parse time.
    plan_from_text — parse the embedded v3 TOML block from markdown.
    providers_used_by_graph — collect backend ids referenced by wave nodes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tripll.skw.validate import extract_toml_block

if TYPE_CHECKING:
    from tripll.graph import RunGraph, WaveNode

VALID_REASONING_EFFORT = frozenset({"low", "medium", "high", "xhigh", "max"})


def validate_reasoning_effort(value: str | None, *, wave_id: str = "") -> str | None:
    """Validate a wave's ``reasoning_effort`` field.

    Args:
        value (str | None): Raw TOML value.
        wave_id (str): Wave id for error messages.

    Returns:
        str | None: Normalised effort, or ``None`` when unset.

    Raises:
        ValueError: When *value* is not one of :data:`VALID_REASONING_EFFORT`.

    Examples:
        >>> validate_reasoning_effort("high")
        'high'
        >>> validate_reasoning_effort(None) is None
        True
    """
    if value is None:
        return None
    effort = str(value).strip().lower()
    if not effort:
        return None
    if effort not in VALID_REASONING_EFFORT:
        label = f"wave {wave_id}: " if wave_id else ""
        raise ValueError(
            f"{label}invalid reasoning_effort={value!r} — "
            f"expected one of {sorted(VALID_REASONING_EFFORT)}"
        )
    return effort


def plan_from_text(text: str) -> dict[str, Any]:
    """Return the parsed v3 plan dict from a markdown body.

    Args:
        text (str): Full plan markdown.

    Returns:
        dict[str, Any]: Parsed plan, or ``{}`` when no TOML block is present.
    """
    data, _err = extract_toml_block(text)
    return dict(data) if data else {}


def wave_node_from_v3(
    wave: dict[str, Any],
    *,
    plan_id: str,
    plan_file: str,
    lane: str,
    owned_paths: list[str],
    node_id_map: dict[str, str],
) -> WaveNode:
    """Build a :class:`~tripll.graph.WaveNode` from one v3 ``[[waves]]`` row.

    Args:
        wave (dict[str, Any]): One wave table from a v3 plan.
        plan_id (str): Plan slug.
        plan_file (str): Plan filename relative to repo root.
        lane (str): Lane display name.
        owned_paths (list[str]): Fallback owned paths when ``targets`` is empty.
        node_id_map (dict[str, str]): wave_id → node_id for dependency resolution.

    Returns:
        WaveNode: Parsed wave node with provider routing fields.
    """
    from tripll.graph import WaveNode

    wave_id = str(wave.get("id", ""))
    node_id = f"{plan_id}:{wave_id}"
    depends: list[str] = []
    for dep in wave.get("depends_on") or []:
        if not isinstance(dep, dict):
            continue
        parent = str(dep.get("wave", ""))
        if parent in node_id_map:
            depends.append(node_id_map[parent])
    targets = [str(t) for t in (wave.get("targets") or [])]
    verify = [str(v) for v in (wave.get("verify") or [])] or ["make ci-affected"]
    effort = str(wave.get("effort") or "M").split()[0]
    wall = 5400 if "XL" in effort.upper() else 2700
    fallback_raw = wave.get("fallback") or []
    fallback = [str(x) for x in fallback_raw] if isinstance(fallback_raw, list) else []
    reasoning = validate_reasoning_effort(wave.get("reasoning_effort"), wave_id=wave_id)
    budget_raw = wave.get("max_budget_usd")
    max_budget: float | None = None
    if budget_raw is not None:
        max_budget = float(budget_raw)
    model_raw = wave.get("model")
    model = str(model_raw).strip() if model_raw is not None else None
    provider_raw = wave.get("provider")
    provider = str(provider_raw).strip() if provider_raw else None
    agent_raw = wave.get("agent")
    agent = str(agent_raw).strip() if agent_raw else None
    role = str(wave.get("role") or "impl")
    human = bool(wave.get("human"))
    decomposition = str(wave.get("decomposition") or "")
    from tripll.harness.quality import parse_wave_outcome

    outcome_raw = wave.get("outcome")
    outcome_contract: dict[str, object] | None = None
    if isinstance(outcome_raw, dict):
        outcome_contract = parse_wave_outcome(
            outcome_raw,
            owned_paths=targets or list(owned_paths),
            wave_decomposition=decomposition,
        )
    return WaveNode(
        node_id=node_id,
        plan_id=plan_id,
        plan_file=plan_file,
        wave_id=wave_id,
        lane=lane,
        owned_paths=targets or list(owned_paths),
        effort=effort,
        wall_clock_limit_s=wall,
        depends_on=depends,
        is_review_gate=human,
        verify_targets=verify,
        model=model or None,
        role=role,
        provider=provider,
        agent=agent,
        fallback=fallback,
        reasoning_effort=reasoning,
        max_budget_usd=max_budget,
        outcome_contract=outcome_contract,
        decomposition=decomposition,
    )


def providers_used_by_graph(graph: RunGraph, default_provider: str) -> set[str]:
    """Collect backend ids that will be dispatched for *graph*.

    Args:
        graph (RunGraph): Parsed run graph.
        default_provider (str): Plan default when a wave omits ``provider``.

    Returns:
        set[str]: Distinct provider backend names.
    """
    names: set[str] = {default_provider}
    for node in graph.nodes.values():
        if node.provider:
            names.add(node.provider)
        names.update(node.fallback)
    return names
