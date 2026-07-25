"""Verifier isolation — separate process/worktree, no implementer transcript (W1.15)."""

from __future__ import annotations

import pytest

from tests.conftest import require_module

_XFAIL = pytest.mark.xfail(reason="green after W7: verifier isolation", strict=False)


@_XFAIL
def test_verify_dispatch_uses_different_process_and_worktree() -> None:
    build_verify_dispatch = require_module("tripll.harness.boundary", attr="build_verify_dispatch")
    ctx = build_verify_dispatch(
        implementer={"process_id": 100, "worktree": "/tmp/wt-impl", "transcript": "secret"},
        wave={"node_id": "p:W2", "commit_sha": "abc123"},
    )
    assert ctx.process_id != 100
    assert ctx.worktree != "/tmp/wt-impl"
    assert ctx.transcript is None


@_XFAIL
def test_isolation_violation_raises() -> None:
    assert_verify_isolation = require_module(
        "tripll.harness.boundary", attr="assert_verify_isolation"
    )
    with pytest.raises((ValueError, RuntimeError), match=r"isolation|transcript|worktree"):
        assert_verify_isolation(
            implementer={"process_id": 1, "worktree": "/same", "transcript": "x"},
            verifier={"process_id": 1, "worktree": "/same", "transcript": "x"},
        )
