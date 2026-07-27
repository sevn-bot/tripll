"""Semantic extraction — adapter dispatch wiring and graph extract --semantic (SEM-03)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

from typer.testing import CliRunner

from tests._fakes import FakeAdapter
from tests.conftest import require_module
from tripll.adapters.base import DispatchResult

if TYPE_CHECKING:
    from tripll.adapters.base import StreamEventCallback


class SemanticFakeAdapter(FakeAdapter):
    """FakeAdapter that echoes IMPLEMENTS assertions for prompt candidates."""

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
        self.calls += 1
        self.dispatched.append(str(brief.get("node_id", "?")))
        prompt = str(brief.get("_prompt_override") or "")
        match = re.search(r"Candidates:\n(\[[\s\S]*\])", prompt)
        items = json.loads(match.group(1)) if match else []
        payload = json.dumps(
            [
                {
                    "predicate": item["predicate"],
                    "src": item["src"],
                    "dst": item["dst"],
                    "confidence": 0.9,
                    "evidence": "fake",
                }
                for item in items
                if isinstance(item, dict)
            ]
        )
        return DispatchResult(
            outcome="done",
            result_text=payload,
            returncode=0,
            log_path=str(log_path),
            argv=self.build_argv(brief, worktree_path),
        )


def test_extract_semantic_batch_dispatches_via_adapter(tmp_path: Path) -> None:
    extract_semantic_batch = require_module(
        "tripll.extract.semantic",
        attr="extract_semantic_batch",
    )
    SemanticCandidate = require_module(
        "tripll.extract.semantic",
        attr="SemanticCandidate",
    )
    adapter = SemanticFakeAdapter()
    candidates = [
        SemanticCandidate(
            predicate="IMPLEMENTS",
            src_id="sym-1",
            dst_id="req-1",
            src_label="mod.fn",
            dst_label="REQ-1",
        )
    ]
    result = extract_semantic_batch(
        candidates,
        repo="tripll",
        worktree_path=tmp_path,
        adapter=adapter,
    )
    assert adapter.calls == 1
    assert len(result.edges) == 1
    assert result.edges[0]["predicate"] == "IMPLEMENTS"
    assert result.edges[0]["src"] == "sym-1"


def test_extract_repo_semantic_pass_upserts_edges(tmp_path: Path) -> None:
    extract_repo = require_module("tripll.extract.pipeline", attr="extract_repo")
    SqliteGraphStore = require_module("tripll.graphstore", attr="SqliteGraphStore")
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "src").mkdir()
    (repo_root / "src" / "mod.py").write_text(
        "def implement_req() -> None:\n    pass\n",
        encoding="utf-8",
    )
    (repo_root / "docs" / "specs").mkdir(parents=True)
    (repo_root / "docs" / "specs" / "req.md").write_text(
        "# Spec\n\nFR-1: Must implement mod.\n",
        encoding="utf-8",
    )
    adapter = SemanticFakeAdapter()
    store = SqliteGraphStore(str(tmp_path / "graph.db"))
    try:
        counts = extract_repo(
            store,
            repo_root,
            repo="tripll",
            sha="abc",
            run_semantic=True,
            adapter=adapter,
        )
    finally:
        store.close()
    assert adapter.calls >= 1
    assert counts.get("semantic_turns", 0) >= 1
    assert counts.get("edges", 0) > 0


def test_graph_extract_semantic_fails_when_backend_unavailable(tmp_path: Path) -> None:
    from tripll.cli import app

    runner = CliRunner()
    with patch("tripll.adapters.get_adapter") as get_adapter:
        adapter = FakeAdapter(available=False)
        get_adapter.return_value = adapter
        result = runner.invoke(
            app,
            [
                "graph",
                "extract",
                "--semantic",
                "--repo-root",
                str(tmp_path),
                "--db",
                str(tmp_path / "g.db"),
            ],
        )
    assert result.exit_code == 1
    assert "unavailable" in result.output.lower()
