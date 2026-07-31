"""tripll.pipeline_spec — declarative agent-pipeline files (``pipeline_format = 1``).

A pipeline file names the steps of an agent pipeline — which agent, system
phase, or human gate runs, in what order, over which transitions — plus the
artifact state each step produces. tripll's own dispatch topology is fixed in
code (``tripll.skw.pipeline``, ``tripll.loops.l1_outer``); this format exists so
a pipeline can be described, diffed, and drawn independently of that code.

Exports:
    StepKind — visual/semantic class of a step.
    TransitionStyle — control-transition class.
    BowSide — side channel hint for transitions back to an earlier layer.
    Transition — one declared transition out of a step.
    Step — one pipeline step.
    State — one artifact state produced by a step.
    Cluster — a named group drawn as a container.
    PipelineSpec — a loaded pipeline file.
    PipelineSpecError — malformed or inconsistent pipeline file.
    load_pipeline_spec — read and validate a ``pipeline_format = 1`` TOML file.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, get_args

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BowSide",
    "Cluster",
    "PipelineSpec",
    "PipelineSpecError",
    "State",
    "Step",
    "StepKind",
    "Transition",
    "TransitionStyle",
    "load_pipeline_spec",
]

StepKind = Literal["agent", "phase", "gate", "external", "artifact"]
TransitionStyle = Literal["primary", "conditional", "optional"]
BowSide = Literal["auto", "left", "right"]

SUPPORTED_FORMAT = 1

_STEP_KEYS = frozenset(
    {
        "id",
        "label",
        "kind",
        "note",
        "work",
        "cluster",
        "produces",
        "wave",
        "layer",
        "column",
        "next",
    }
)
_TRANSITION_KEYS = frozenset({"to", "label", "note", "style", "bow"})
_STATE_KEYS = frozenset({"id", "label", "kind", "note", "layer", "column"})
_CLUSTER_KEYS = frozenset({"id", "label", "states"})


class PipelineSpecError(ValueError):
    """Raised when a pipeline file is malformed or internally inconsistent."""


@dataclass(frozen=True)
class Transition:
    """One declared transition out of a step.

    Args:
        to (str): Target step id.
        label (str): Transition label (the condition or hand-off).
        note (str): Optional second label line.
        style (TransitionStyle): Control-transition class.
        bow (BowSide): Side channel for transitions back to an earlier layer.
    """

    to: str
    label: str = ""
    note: str = ""
    style: TransitionStyle = "primary"
    bow: BowSide = "auto"


@dataclass(frozen=True)
class Step:
    """One pipeline step.

    Args:
        step_id (str): Unique id; also the default label (e.g. an agent id).
        label (str): Node label in the execution view.
        kind (StepKind): Visual/semantic class.
        note (str): Optional second label line.
        work (str): Name used on state-view edges; defaults to ``label``.
        cluster (str): Cluster id, or ``''``.
        produces (str): State id this step advances the pipeline to, or ``''``.
        wave (str): Primary label for the produced state's incoming edge.
        layer (int | None): Explicit row, or None to derive it.
        column (float | None): Explicit column, or None to derive it.
        transitions (tuple[Transition, ...]): Outgoing transitions.
    """

    step_id: str
    label: str
    kind: StepKind = "agent"
    note: str = ""
    work: str = ""
    cluster: str = ""
    produces: str = ""
    wave: str = ""
    layer: int | None = None
    column: float | None = None
    transitions: tuple[Transition, ...] = ()

    @property
    def work_label(self) -> str:
        """Return the name to show on state-view edges.

        Returns:
            str: ``work`` when set, otherwise ``label``.

        Examples:
            >>> Step("a", "Agent A").work_label
            'Agent A'
        """
        return self.work or self.label


@dataclass(frozen=True)
class State:
    """One artifact state.

    Args:
        state_id (str): Unique id referenced by ``Step.produces``.
        label (str): Node label in the state view.
        kind (StepKind): Visual class (defaults to ``artifact``).
        note (str): Optional second label line.
        layer (int | None): Explicit row, or None to derive it.
        column (float | None): Explicit column, or None to derive it.
    """

    state_id: str
    label: str
    kind: StepKind = "artifact"
    note: str = ""
    layer: int | None = None
    column: float | None = None


@dataclass(frozen=True)
class Cluster:
    """A named group drawn as a labelled container.

    Args:
        cluster_id (str): Id referenced by ``Step.cluster``.
        label (str): Container heading.
        states (tuple[str, ...]): State ids grouped in the state view.
    """

    cluster_id: str
    label: str
    states: tuple[str, ...] = ()


@dataclass(frozen=True)
class PipelineSpec:
    """A loaded pipeline file.

    Args:
        title (str): Pipeline title.
        slug (str): Short id used for filenames.
        description (str): One-line description.
        steps (tuple[Step, ...]): Steps in declaration order.
        states (tuple[State, ...]): Declared states in declaration order.
        clusters (tuple[Cluster, ...]): Declared clusters.
        source (str): Path the spec was loaded from.
    """

    title: str
    slug: str
    description: str
    steps: tuple[Step, ...]
    states: tuple[State, ...] = ()
    clusters: tuple[Cluster, ...] = ()
    source: str = ""

    def step_map(self) -> dict[str, Step]:
        """Return step_id → step.

        Returns:
            dict[str, Step]: Lookup in declaration order.

        Examples:
            >>> PipelineSpec("t", "s", "", (Step("a", "A"),)).step_map()["a"].label
            'A'
        """
        return {step.step_id: step for step in self.steps}

    def state_map(self) -> dict[str, State]:
        """Return state_id → state, including states only named by ``produces``.

        States referenced by a step but never declared get a fallback entry so a
        partial file still renders.

        Returns:
            dict[str, State]: Lookup in declaration order, declared first.

        Examples:
            >>> spec = PipelineSpec("t", "s", "", (Step("a", "A", produces="x"),))
            >>> spec.state_map()["x"].label
            'x'
        """
        out = {state.state_id: state for state in self.states}
        for step in self.steps:
            if step.produces and step.produces not in out:
                out[step.produces] = State(state_id=step.produces, label=step.produces)
        return out

    def incoming(self) -> dict[str, list[tuple[str, Transition]]]:
        """Return target step id → list of ``(source_step_id, transition)``.

        Returns:
            dict[str, list[tuple[str, Transition]]]: Reverse adjacency.

        Examples:
            >>> spec = PipelineSpec("t", "s", "", (
            ...     Step("a", "A", transitions=(Transition("b"),)), Step("b", "B")))
            >>> spec.incoming()["b"][0][0]
            'a'
        """
        out: dict[str, list[tuple[str, Transition]]] = {step.step_id: [] for step in self.steps}
        for step in self.steps:
            for transition in step.transitions:
                out.setdefault(transition.to, []).append((step.step_id, transition))
        return out


def _require_str(value: Any, where: str, key: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        msg = f"{where}: {key} must be a string, got {type(value).__name__}"
        raise PipelineSpecError(msg)
    return value


def _optional_number(value: Any, where: str, key: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"{where}: {key} must be a number, got {type(value).__name__}"
        raise PipelineSpecError(msg)
    return float(value)


def _check_choice(value: str, allowed: tuple[str, ...], where: str, key: str) -> str:
    if value and value not in allowed:
        msg = f"{where}: unknown {key} {value!r} (expected one of {', '.join(allowed)})"
        raise PipelineSpecError(msg)
    return value


def _check_keys(table: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    unknown = sorted(set(table) - allowed)
    if unknown:
        msg = f"{where}: unknown key(s) {', '.join(unknown)}"
        raise PipelineSpecError(msg)


def _parse_transition(raw: Any, where: str) -> Transition:
    if not isinstance(raw, dict):
        msg = f"{where}: each [[steps.next]] entry must be a table"
        raise PipelineSpecError(msg)
    _check_keys(raw, _TRANSITION_KEYS, where)
    to = _require_str(raw.get("to"), where, "to")
    if not to:
        msg = f"{where}: [[steps.next]] requires 'to'"
        raise PipelineSpecError(msg)
    style = _check_choice(
        _require_str(raw.get("style"), where, "style"), get_args(TransitionStyle), where, "style"
    )
    bow = _check_choice(_require_str(raw.get("bow"), where, "bow"), get_args(BowSide), where, "bow")
    return Transition(
        to=to,
        label=_require_str(raw.get("label"), where, "label"),
        note=_require_str(raw.get("note"), where, "note"),
        style=style or "primary",  # type: ignore[arg-type]
        bow=bow or "auto",  # type: ignore[arg-type]
    )


def _parse_step(raw: Any, index: int) -> Step:
    where = f"[[steps]] #{index + 1}"
    if not isinstance(raw, dict):
        msg = f"{where}: each entry must be a table"
        raise PipelineSpecError(msg)
    _check_keys(raw, _STEP_KEYS, where)
    step_id = _require_str(raw.get("id"), where, "id")
    if not step_id:
        msg = f"{where}: requires 'id'"
        raise PipelineSpecError(msg)
    where = f"step {step_id!r}"
    kind = _check_choice(
        _require_str(raw.get("kind"), where, "kind"), get_args(StepKind), where, "kind"
    )
    layer = _optional_number(raw.get("layer"), where, "layer")
    transitions = tuple(_parse_transition(entry, where) for entry in raw.get("next", []) or ())
    return Step(
        step_id=step_id,
        label=_require_str(raw.get("label"), where, "label") or step_id,
        kind=kind or "agent",  # type: ignore[arg-type]
        note=_require_str(raw.get("note"), where, "note"),
        work=_require_str(raw.get("work"), where, "work"),
        cluster=_require_str(raw.get("cluster"), where, "cluster"),
        produces=_require_str(raw.get("produces"), where, "produces"),
        wave=_require_str(raw.get("wave"), where, "wave"),
        layer=None if layer is None else int(layer),
        column=_optional_number(raw.get("column"), where, "column"),
        transitions=transitions,
    )


def _parse_state(raw: Any, index: int) -> State:
    where = f"[[states]] #{index + 1}"
    if not isinstance(raw, dict):
        msg = f"{where}: each entry must be a table"
        raise PipelineSpecError(msg)
    _check_keys(raw, _STATE_KEYS, where)
    state_id = _require_str(raw.get("id"), where, "id")
    if not state_id:
        msg = f"{where}: requires 'id'"
        raise PipelineSpecError(msg)
    where = f"state {state_id!r}"
    kind = _check_choice(
        _require_str(raw.get("kind"), where, "kind"), get_args(StepKind), where, "kind"
    )
    layer = _optional_number(raw.get("layer"), where, "layer")
    return State(
        state_id=state_id,
        label=_require_str(raw.get("label"), where, "label") or state_id,
        kind=kind or "artifact",  # type: ignore[arg-type]
        note=_require_str(raw.get("note"), where, "note"),
        layer=None if layer is None else int(layer),
        column=_optional_number(raw.get("column"), where, "column"),
    )


def _parse_cluster(raw: Any, index: int) -> Cluster:
    where = f"[[clusters]] #{index + 1}"
    if not isinstance(raw, dict):
        msg = f"{where}: each entry must be a table"
        raise PipelineSpecError(msg)
    _check_keys(raw, _CLUSTER_KEYS, where)
    cluster_id = _require_str(raw.get("id"), where, "id")
    if not cluster_id:
        msg = f"{where}: requires 'id'"
        raise PipelineSpecError(msg)
    states = raw.get("states", []) or []
    if not isinstance(states, list):
        msg = f"cluster {cluster_id!r}: states must be an array"
        raise PipelineSpecError(msg)
    return Cluster(
        cluster_id=cluster_id,
        label=_require_str(raw.get("label"), where, "label") or cluster_id,
        states=tuple(str(item) for item in states),
    )


@dataclass
class _CrossRefs:
    """Collected id sets for cross-reference checks."""

    steps: set[str] = field(default_factory=set)
    states: set[str] = field(default_factory=set)
    clusters: set[str] = field(default_factory=set)


def _check_cross_refs(spec: PipelineSpec) -> None:
    refs = _CrossRefs(
        steps={s.step_id for s in spec.steps},
        states={s.state_id for s in spec.states},
        clusters={c.cluster_id for c in spec.clusters},
    )
    errors: list[str] = []
    for step in spec.steps:
        for transition in step.transitions:
            if transition.to not in refs.steps:
                errors.append(
                    f"step {step.step_id!r}: transition to unknown step {transition.to!r}"
                )
        if step.cluster and step.cluster not in refs.clusters:
            errors.append(f"step {step.step_id!r}: unknown cluster {step.cluster!r}")
        if step.produces and refs.states and step.produces not in refs.states:
            errors.append(f"step {step.step_id!r}: produces undeclared state {step.produces!r}")
    for cluster in spec.clusters:
        for state_id in cluster.states:
            if refs.states and state_id not in refs.states:
                errors.append(f"cluster {cluster.cluster_id!r}: unknown state {state_id!r}")
    if errors:
        raise PipelineSpecError("; ".join(errors))


def _check_duplicates(items: list[str], noun: str) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for item in items:
        if item in seen:
            duplicates.add(item)
        seen.add(item)
    if duplicates:
        msg = f"duplicate {noun} id(s): {', '.join(sorted(duplicates))}"
        raise PipelineSpecError(msg)


def load_pipeline_spec(path: Path) -> PipelineSpec:
    """Read and validate a ``pipeline_format = 1`` TOML pipeline file.

    Args:
        path (Path): Path to the pipeline file.

    Returns:
        PipelineSpec: Validated spec.

    Raises:
        PipelineSpecError: If the file is unreadable, declares an unsupported
            format version, has duplicate ids, or references unknown ids.

    Examples:
        >>> load_pipeline_spec(Path("docs/examples/pipelines/tripll-l1-pipeline.toml"))  # doctest: +SKIP
        PipelineSpec(title='tripll L1 pipeline', ...)
    """
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"cannot read pipeline file {path}: {exc}"
        raise PipelineSpecError(msg) from exc
    except tomllib.TOMLDecodeError as exc:
        msg = f"invalid TOML in {path}: {exc}"
        raise PipelineSpecError(msg) from exc

    version = raw.get("pipeline_format")
    if version != SUPPORTED_FORMAT:
        msg = f"{path}: pipeline_format must be {SUPPORTED_FORMAT}, got {version!r}"
        raise PipelineSpecError(msg)

    steps_raw = raw.get("steps") or []
    if not isinstance(steps_raw, list) or not steps_raw:
        msg = f"{path}: at least one [[steps]] entry is required"
        raise PipelineSpecError(msg)

    steps = tuple(_parse_step(entry, index) for index, entry in enumerate(steps_raw))
    states = tuple(
        _parse_state(entry, index) for index, entry in enumerate(raw.get("states") or [])
    )
    clusters = tuple(
        _parse_cluster(entry, index) for index, entry in enumerate(raw.get("clusters") or [])
    )
    _check_duplicates([s.step_id for s in steps], "step")
    _check_duplicates([s.state_id for s in states], "state")
    _check_duplicates([c.cluster_id for c in clusters], "cluster")

    spec = PipelineSpec(
        title=_require_str(raw.get("title"), str(path), "title") or path.stem,
        slug=_require_str(raw.get("slug"), str(path), "slug") or path.stem,
        description=_require_str(raw.get("description"), str(path), "description"),
        steps=steps,
        states=states,
        clusters=clusters,
        source=str(path),
    )
    _check_cross_refs(spec)
    return spec
