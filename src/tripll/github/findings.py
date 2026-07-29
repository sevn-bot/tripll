"""Finding schema, normalization, dedup, ABOUT resolution, and graph ingestion."""

from __future__ import annotations

import hashlib
import json
import re
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any

from tripll.extract._common import edge_id, provenance, utc_now
from tripll.graphstore import GraphStore, SqliteGraphStore

_EXTRACTOR = "github.findings"
_EXTRACTOR_VERSION = "1"

_RULE_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+)(?::\d+)?\s+(?P<code>[A-Z]\d+)\b",
    re.MULTILINE,
)
_RUFF_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+)(?::\d+)?\s+(?P<code>[A-Z]\d+)\b",
    re.MULTILINE,
)
# mergeCraft triage tag: `_Category_ | _Severity_ | _Effort_`
_MERGECRAFT_TRIAGE = re.compile(
    r"^_(?P<category>[^_]+)_ \| _(?P<severity>[^_]+)_ \| _(?P<effort>[^_]+)_",
    re.MULTILINE,
)
_SUGGESTION_FENCE = re.compile(
    r"```suggestion\n(?P<body>.*?)\n```",
    re.DOTALL,
)

_SEVERITY_MAP = {
    "critical": "critical",
    "major": "high",
    "minor": "medium",
    "trivial": "low",
}


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _normalize_message(text: str) -> str:
    collapsed = " ".join(text.strip().split())
    return collapsed.lower()


def _finding_id(dedup_key: tuple[str, ...]) -> str:
    digest = hashlib.sha256("|".join(dedup_key).encode()).hexdigest()[:16]
    return digest


def _parse_rule_from_output(text: str) -> tuple[str | None, str | None, list[int] | None, str]:
    """Return (rule_id, file, line_range, message_normalized) from check output text."""
    for pattern in (_RUFF_LINE, _RULE_LINE):
        match = pattern.search(text)
        if match:
            file_ = match.group("file")
            line = int(match.group("line"))
            code = match.group("code")
            rule_id = f"ruff:{code}" if code[0].isalpha() else code
            return rule_id, file_, [line, line], _normalize_message(text)
    return None, None, None, _normalize_message(text)


def _review_rule_id(raw: dict[str, Any]) -> str:
    login = str((raw.get("user") or {}).get("login", "")).lower()
    # mergeCraft bot (+ legacy pullfrog during transition).
    if login in {"mergecraft[bot]", "mergecraft", "pullfrog"} or login.startswith("mergecraft"):
        return "mergecraft:review"
    if "bugbot" in login:
        return "bugbot:review"
    if login:
        return f"review:{login}"
    return "review:comment"


def _store_from_arg(graph_store: GraphStore | str) -> GraphStore:
    if isinstance(graph_store, str):
        return SqliteGraphStore(graph_store)
    return graph_store


def normalize_check_run(raw: dict[str, Any], *, run_id: str = "local") -> dict[str, Any]:
    """Normalize a GitHub check-run payload into the Finding schema (§7.12.2)."""
    output = raw.get("output") or {}
    text = str(output.get("text") or output.get("summary") or "")
    title = str(output.get("title") or raw.get("name") or "check")
    rule_id, file_, line_range, message_norm = _parse_rule_from_output(text)
    if rule_id is None:
        name = str(raw.get("name") or "check").lower()
        rule_id = f"ci:{name}"
    head_sha = str(raw.get("head_sha") or "")
    check_id = raw.get("id")
    source = f"check_run:{check_id}" if check_id is not None else str(raw.get("html_url") or "")
    dedup = (rule_id, file_ or "", "", message_norm)
    return {
        "finding_id": _finding_id(dedup),
        "run_id": run_id,
        "kind": "ci_check",
        "source": source,
        "rule_id": rule_id,
        "severity": "high" if raw.get("conclusion") == "failure" else "info",
        "file": file_,
        "line_range": line_range,
        "symbol_ref": None,
        "message_raw": text or title,
        "message_normalized": message_norm,
        "raised_at": _now(),
        "head_sha": head_sha,
        "state": "open" if raw.get("conclusion") == "failure" else "fixed",
        "confidence": 1.0,
        "evidence": str(raw.get("html_url") or text[:500]),
        "extractor": _EXTRACTOR,
        "extractor_version": _EXTRACTOR_VERSION,
    }


def _parse_mergecraft_triage(body: str) -> dict[str, str | None]:
    """Extract category / severity / effort / suggestion from a mergeCraft comment body."""
    match = _MERGECRAFT_TRIAGE.search(body)
    category = match.group("category").strip() if match else None
    raw_sev = match.group("severity").strip().lower() if match else None
    effort = match.group("effort").strip() if match else None
    severity = _SEVERITY_MAP.get(raw_sev or "", "medium") if raw_sev else None
    sug = _SUGGESTION_FENCE.search(body)
    suggestion = sug.group("body") if sug else None
    return {
        "category": category,
        "severity": severity,
        "effort": effort,
        "suggestion": suggestion,
    }


def normalize_review_comment(raw: dict[str, Any], *, run_id: str = "local") -> dict[str, Any]:
    """Normalize an inline PR review comment into the Finding schema.

    When the comment is from mergeCraft and carries a triage tag line
    (``_Category_ | _Severity_ | _Effort_``), those fields are promoted onto
    the Finding. GitHub suggestion fences become ``suggestion`` for fix agents.
    """
    file_ = str(raw.get("path") or raw.get("file") or "")
    line = raw.get("line") or raw.get("original_line")
    line_range = [int(line), int(line)] if line is not None else None
    body = str(raw.get("body") or "")
    rule_id = _review_rule_id(raw)
    message_norm = _normalize_message(body)
    dedup = (rule_id, file_, "", message_norm)
    comment_id = raw.get("id")
    source = (
        f"review_comment:{comment_id}" if comment_id is not None else str(raw.get("html_url") or "")
    )
    triage = _parse_mergecraft_triage(body) if rule_id == "mergecraft:review" else {}
    return {
        "finding_id": _finding_id(dedup),
        "run_id": run_id,
        "kind": "review_comment",
        "source": source,
        "rule_id": rule_id,
        "severity": triage.get("severity") or "medium",
        "category": triage.get("category"),
        "effort": triage.get("effort"),
        "suggestion": triage.get("suggestion"),
        "file": file_ or None,
        "line_range": line_range,
        "symbol_ref": None,
        "message_raw": body,
        "message_normalized": message_norm,
        "raised_at": _now(),
        "head_sha": str(raw.get("commit_id") or raw.get("head_sha") or ""),
        "state": "open",
        "confidence": 1.0,
        "evidence": str(raw.get("html_url") or body[:500]),
        "extractor": _EXTRACTOR,
        "extractor_version": _EXTRACTOR_VERSION,
    }


def dedup_key(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    """Return the dedup tuple (rule_id, file, symbol_ref, message_normalized)."""
    return (
        str(finding.get("rule_id") or ""),
        str(finding.get("file") or ""),
        str(finding.get("symbol_ref") or ""),
        str(finding.get("message_normalized") or ""),
    )


def dedup_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse findings sharing the same dedup key, keeping the first."""
    seen: set[tuple[str, str, str, str]] = set()
    out: list[dict[str, Any]] = []
    for finding in findings:
        key = dedup_key(finding)
        if key in seen:
            continue
        seen.add(key)
        out.append(finding)
    return out


def _query_symbols(store: GraphStore, file_: str) -> list[Any]:
    """Return Symbol rows whose path matches *file_*."""
    if isinstance(store, SqliteGraphStore):
        return store.conn.execute(
            """SELECT node_id, natural_key, props, evidence, valid_to_sha
               FROM nodes
               WHERE layer = 'code' AND kind = 'Symbol' AND valid_to IS NULL
                 AND (props LIKE ? OR natural_key LIKE ?)""",
            (f'%"path": "{file_}"%', f"%#{file_}::%"),
        ).fetchall()
    return []


def resolve_about(
    finding: dict[str, Any],
    graph_store: GraphStore | str,
    *,
    repo: str = "tripll",
) -> str:
    """Resolve a finding's file/line to a Symbol node_id via the Code KG."""
    store = _store_from_arg(graph_store)
    file_ = str(finding.get("file") or "")
    line_range = finding.get("line_range") or []
    target_line = int(line_range[0]) if line_range else None

    rows = _query_symbols(store, file_)

    best_id: str | None = None
    best_line = -1
    for row in rows:
        props_raw = row["props"]
        try:
            props = json.loads(props_raw) if props_raw else {}
        except json.JSONDecodeError:
            props = {}
        path = str(props.get("path") or "")
        if path and path != file_:
            continue
        evidence = str(row["evidence"] or "")
        line_hint = target_line
        if evidence and ":" in evidence:
            with suppress(ValueError):
                line_hint = int(evidence.rsplit(":", 1)[-1])
        if target_line is not None and line_hint is not None:
            if line_hint <= target_line and line_hint >= best_line:
                best_line = line_hint
                best_id = str(row["node_id"])
        elif best_id is None:
            best_id = str(row["node_id"])

    if best_id:
        return best_id

    qualname = file_.rsplit("/", 1)[-1].removesuffix(".py") if file_ else "module"
    natural_key = f"{repo}#{file_}::{qualname}" if file_ else f"{repo}#::{qualname}"
    return f"code:Symbol:{natural_key}"


def is_stale(finding: dict[str, Any], *, current_head: str) -> bool:
    """True when head_sha differs from current_head and ABOUT target has valid_to_sha (§7.12.3)."""
    head = str(finding.get("head_sha") or "")
    if not head or head == current_head:
        return False
    about = finding.get("about_target") or {}
    valid_to = about.get("valid_to_sha")
    return valid_to is not None and str(valid_to) != ""


def finding_to_graph_nodes(
    finding: dict[str, Any],
    *,
    repo: str = "tripll",
    symbol_id: str | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a Finding node and optional ABOUT edge for GraphStore upsert."""
    run_id = str(finding.get("run_id") or "local")
    finding_id = str(finding.get("finding_id") or _finding_id(dedup_key(finding)))
    natural_key = f"{run_id}#{finding_id}"
    node_id = f"finding:Finding:{natural_key}"
    props = {k: v for k, v in finding.items() if k not in {"symbol_ref", "about_target"}}
    prov = provenance(
        source=str(finding.get("source") or "github"),
        evidence=str(finding.get("evidence") or ""),
        extractor=_EXTRACTOR,
        confidence=float(finding.get("confidence") or 1.0),
        extracted_at=str(finding.get("raised_at") or utc_now()),
    )
    node = {
        "node_id": node_id,
        "layer": "finding",
        "kind": "Finding",
        "natural_key": natural_key,
        "repo": repo,
        "props": json.dumps(props),
        **prov,
    }
    edges: list[dict[str, Any]] = []
    sym = symbol_id or finding.get("symbol_ref")
    if sym:
        edges.append(
            {
                "edge_id": edge_id("ABOUT", node_id, str(sym)),
                "predicate": "ABOUT",
                "src": node_id,
                "dst": str(sym),
                **prov,
            }
        )
    return node, edges


def sync_findings_to_store(
    findings: list[dict[str, Any]],
    store: GraphStore,
    *,
    repo: str = "tripll",
    resolve_symbols: bool = True,
) -> int:
    """Upsert normalized findings into the graph with ABOUT edges."""
    collapsed = dedup_findings(findings)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for finding in collapsed:
        sym: str | None = None
        if resolve_symbols and finding.get("file"):
            sym = resolve_about(finding, store, repo=repo)
            finding = {**finding, "symbol_ref": sym}
        node, about_edges = finding_to_graph_nodes(finding, repo=repo, symbol_id=sym)
        nodes.append(node)
        edges.extend(about_edges)
    if nodes:
        store.upsert_nodes(nodes)
    if edges:
        store.upsert_edges(edges)
    return len(nodes)


def _list_finding_rows(store: GraphStore) -> list[Any]:
    if isinstance(store, SqliteGraphStore):
        return store.conn.execute(
            """SELECT node_id, props FROM nodes
               WHERE layer = 'finding' AND kind = 'Finding' AND valid_to IS NULL"""
        ).fetchall()
    return []


def list_findings_from_store(
    store: GraphStore,
    *,
    state: str | None = None,
) -> list[dict[str, Any]]:
    """Load Finding nodes from the graph, optionally filtered by state."""
    rows = _list_finding_rows(store)
    out: list[dict[str, Any]] = []
    for row in rows:
        try:
            props = json.loads(str(row["props"]))
        except json.JSONDecodeError:
            continue
        props["node_id"] = str(row["node_id"])
        if state is not None and props.get("state") != state:
            continue
        out.append(props)
    return out


def triage_finding(
    finding: dict[str, Any],
    *,
    state: str,
    rationale: str | None = None,
) -> dict[str, Any]:
    """Update finding state (accepted/rejected/deferred) with optional rationale."""
    updated = dict(finding)
    updated["state"] = state
    if rationale:
        updated["rationale"] = rationale
    return updated
