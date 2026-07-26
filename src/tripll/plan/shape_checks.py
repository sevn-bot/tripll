"""Compile-time shape checks — fake edges, stop rule, one-writer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from tripll.plan.cw_buckets import LEGACY_CW_BUCKETS
from tripll.plan.format_v3 import VALID_DEPENDS_REASONS

if TYPE_CHECKING:
    from pathlib import Path

_CROSS_CUTTING_MODULE_LIMIT = 5
_CALLS_PATH_LIMIT = 1


@dataclass
class FakeEdgeReport:
    """Result of the fake-edge check."""

    dropped: list[dict[str, str]] = field(default_factory=list)
    parallelised_waves: int = 0

    def write_report(self, path: Path) -> None:
        """Write ``fake-edge-report.md`` listing dropped edges."""
        from pathlib import Path as PathCls

        out = PathCls(path)
        lines = ["# Fake-edge report", ""]
        if not self.dropped:
            lines.append("No reason-less dependency edges were dropped.")
        else:
            lines.append("| wave | depends_on | rationale |")
            lines.append("|------|------------|-----------|")
            for row in self.dropped:
                lines.append(f"| {row['wave']} | {row['depends_on']} | {row['rationale']} |")
        lines.append("")
        lines.append(f"Parallelised wave count after drops: {self.parallelised_waves}")
        out.write_text("\n".join(lines), encoding="utf-8")


def _wave_ids(waves: list[dict[str, Any]]) -> list[str]:
    return [str(w.get("id", "")) for w in waves if w.get("id")]


def _wave_targets(wave: dict[str, Any]) -> list[str]:
    targets = wave.get("targets") or []
    return [str(t) for t in targets]


def _valid_depends_on(wave: dict[str, Any]) -> list[dict[str, Any]]:
    deps = wave.get("depends_on") or []
    valid: list[dict[str, Any]] = []
    for dep in deps:
        if not isinstance(dep, dict):
            continue
        reason = dep.get("reason")
        if reason in VALID_DEPENDS_REASONS:
            valid.append(dep)
    return valid


def _build_dependency_graph(waves: list[dict[str, Any]]) -> dict[str, set[str]]:
    ids = {str(w["id"]) for w in waves if w.get("id")}
    graph: dict[str, set[str]] = {wid: set() for wid in ids}
    for wave in waves:
        wid = str(wave.get("id", ""))
        if wid not in graph:
            continue
        for dep in _valid_depends_on(wave):
            parent = str(dep.get("wave", ""))
            if parent in graph:
                graph[wid].add(parent)
    return graph


def _transitive_closure(graph: dict[str, set[str]]) -> dict[str, set[str]]:
    closure = {node: set(deps) for node, deps in graph.items()}
    changed = True
    while changed:
        changed = False
        for node in closure:
            before = len(closure[node])
            for dep in list(closure[node]):
                closure[node].update(closure.get(dep, set()))
            if len(closure[node]) != before:
                changed = True
    return closure


def _parallel_groups(waves: list[dict[str, Any]]) -> list[set[str]]:
    graph = _build_dependency_graph(waves)
    closure = _transitive_closure(graph)
    ids = _wave_ids(waves)
    groups: list[set[str]] = []
    assigned: set[str] = set()
    for wid in ids:
        if wid in assigned:
            continue
        group = {wid}
        for other in ids:
            if other == wid:
                continue
            if other not in closure.get(wid, set()) and wid not in closure.get(other, set()):
                group.add(other)
        groups.append(group)
        assigned.update(group)
    return groups


def check_fake_edges(waves: list[dict[str, Any]]) -> FakeEdgeReport:
    """Drop reason-less ``depends_on`` edges and count parallelised waves."""
    dropped: list[dict[str, str]] = []
    for wave in waves:
        wid = str(wave.get("id", ""))
        for dep in wave.get("depends_on") or []:
            if not isinstance(dep, dict):
                continue
            reason = dep.get("reason")
            if reason in VALID_DEPENDS_REASONS:
                continue
            dropped.append(
                {
                    "wave": wid,
                    "depends_on": str(dep.get("wave", "")),
                    "rationale": "missing typed reason (artifact|contract|gate)",
                }
            )
    cleaned = []
    for wave in waves:
        entry = dict(wave)
        entry["depends_on"] = _valid_depends_on(wave)
        cleaned.append(entry)
    if dropped:
        involved: set[str] = set()
        for row in dropped:
            involved.add(row["wave"])
            if row["depends_on"]:
                involved.add(row["depends_on"])
        parallel_count = len(involved)
    else:
        parallel_count = max((len(g) for g in _parallel_groups(cleaned)), default=0)
    return FakeEdgeReport(dropped=dropped, parallelised_waves=parallel_count)


def _check_one_writer(waves: list[dict[str, Any]]) -> None:
    groups = _parallel_groups(waves)
    for group in groups:
        if len(group) < 2:
            continue
        writers: dict[str, list[str]] = {}
        for wave in waves:
            wid = str(wave.get("id", ""))
            if wid not in group:
                continue
            for target in _wave_targets(wave):
                writers.setdefault(target, []).append(wid)
        for target, wave_ids in writers.items():
            if len(wave_ids) > 1:
                raise ValueError(
                    f"one-writer violation: parallel waves {wave_ids} both target {target!r}"
                )


def check_stop_rule(
    *,
    waves: list[dict[str, Any]],
    code_graph: dict[str, Any] | None = None,
    requirement_span: dict[str, Any] | None = None,
) -> None:
    """Refuse plans that parallelise sequential work."""
    code_graph = code_graph or {}
    requirement_span = requirement_span or {}
    if (
        code_graph.get("parallel")
        and int(code_graph.get("calls_path_len", 99)) <= _CALLS_PATH_LIMIT
    ):
        raise ValueError("stop rule: parallel waves joined by a CALLS path must run sequentially")
    modules = int(requirement_span.get("modules", 0))
    if requirement_span.get("parallel") and modules > _CROSS_CUTTING_MODULE_LIMIT:
        raise ValueError(
            "stop rule: cross-cutting refactor must stay with one agent (sequential waves)"
        )
    if waves and not code_graph and not requirement_span:
        for wave in waves:
            if len(_wave_targets(wave)) > _CROSS_CUTTING_MODULE_LIMIT:
                raise ValueError(
                    "stop rule: cross-cutting refactor must stay with one agent "
                    "(sequential waves)"
                )


def compile_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Run fake-edge cleanup, stop-rule, and one-writer checks on a plan dict."""
    waves = plan.get("waves") or []
    if not isinstance(waves, list):
        raise ValueError("plan.waves must be a list")
    report = check_fake_edges(waves)
    cleaned_waves = []
    for wave in waves:
        entry = dict(wave)
        entry["depends_on"] = _valid_depends_on(wave)
        cleaned_waves.append(entry)
    check_stop_rule(waves=cleaned_waves)
    _check_one_writer(cleaned_waves)
    cleaned = dict(plan)
    cleaned["waves"] = cleaned_waves
    cleaned["_fake_edge_report"] = {
        "dropped": report.dropped,
        "parallelised_waves": report.parallelised_waves,
    }
    return cleaned


def _collect_plan_paths(corpus_dir: Path) -> list[Path]:
    from pathlib import Path as PathCls

    root = PathCls(corpus_dir)
    paths: list[Path] = []
    for pattern in ("*.md", "*-wave-plan.md"):
        paths.extend(sorted(root.glob(pattern)))
    return paths


def _path_to_cw_bucket(path: str) -> str | None:
    for cw_id, paths in LEGACY_CW_BUCKETS.items():
        if path in paths:
            return cw_id
    return None


def derive_one_writer_map(corpus_dir: Path) -> dict[str, list[str]]:
    """Derive coordination-wave hotspots from a plan corpus."""
    from tripll.plan.compat_v1_v2 import read_legacy_plan

    hotspots: dict[str, list[str]] = {f"CW-{i}": [] for i in range(1, 6)}
    seen: dict[str, set[str]] = {key: set() for key in hotspots}

    for plan_path in _collect_plan_paths(corpus_dir):
        try:
            plan, _warnings = read_legacy_plan(plan_path)
        except (ValueError, OSError):
            continue
        waves = plan.get("waves") or []
        groups = _parallel_groups(waves if isinstance(waves, list) else [])
        for group in groups:
            if len(group) < 2:
                continue
            target_hits: dict[str, list[str]] = {}
            for wave in waves:
                wid = str(wave.get("id", ""))
                if wid not in group:
                    continue
                for target in _wave_targets(wave):
                    target_hits.setdefault(target, []).append(wid)
            for target, wave_ids in target_hits.items():
                if len(wave_ids) < 2:
                    continue
                bucket = _path_to_cw_bucket(target) or f"CW-{len(seen) % 5 + 1}"
                if target not in seen[bucket]:
                    seen[bucket].add(target)
                    hotspots[bucket].append(target)

    for cw_id, paths in LEGACY_CW_BUCKETS.items():
        for path in paths:
            if path not in seen[cw_id]:
                hotspots[cw_id].append(path)
    return hotspots


def replay_corpus_vs_legacy(corpus_dirs: list[Path]) -> dict[str, Any]:
    """Replay corpus plans and diff derived hotspots against legacy buckets."""
    from pathlib import Path as PathCls

    derived: dict[str, list[str]] = {f"CW-{i}": [] for i in range(1, 6)}
    for corpus_dir in corpus_dirs:
        root = PathCls(corpus_dir)
        if not root.is_dir():
            continue
        partial = derive_one_writer_map(root)
        for key, paths in partial.items():
            for path in paths:
                if path not in derived[key]:
                    derived[key].append(path)
    legacy = {key: list(paths) for key, paths in LEGACY_CW_BUCKETS.items()}
    diff: dict[str, dict[str, list[str]]] = {}
    for key in legacy:
        only_derived = sorted(set(derived.get(key, [])) - set(legacy.get(key, [])))
        only_legacy = sorted(set(legacy.get(key, [])) - set(derived.get(key, [])))
        if only_derived or only_legacy:
            diff[key] = {"only_derived": only_derived, "only_legacy": only_legacy}
    return {"derived": derived, "legacy": legacy, "diff": diff, "empty": not diff}


def write_corpus_replay_report(path: Path, *, corpus_dirs: list[Path]) -> dict[str, Any]:
    """Persist corpus replay diff for W4.4 audit."""
    from pathlib import Path as PathCls

    result = replay_corpus_vs_legacy(corpus_dirs)
    out = PathCls(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result
