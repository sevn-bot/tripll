from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tripll import build_plan_from_errors as driver
from tripll.adapters.base import AdapterCapabilities, DispatchResult


def safe_turn_id(turn_id: str) -> str:
    return turn_id.replace(":", "_").replace("=", "_").replace("/", "_")


def _write_bundle_jsonl(
    path: Path, *, turn_id: str, session_id: str, channel: str, terminal_status: str
) -> None:
    """Write one-turn bundle JSONL with a valid ``meta`` line only."""
    meta = {
        "stream": "meta",
        "turn_id": turn_id,
        "session_id": session_id,
        "channel": channel,
        "terminal_status": terminal_status,
        "created_at": "2026-06-16T00:00:00+00:00",
    }
    path.write_text(json.dumps(meta) + "\n", encoding="utf-8")


def _bundle_index_entry(
    *,
    turn_id: str,
    session_id: str,
    channel: str,
    terminal_status: str,
    processed: bool,
    has_error: bool,
) -> dict[str, Any]:
    return {
        "turn_id": turn_id,
        "file": f"{safe_turn_id(turn_id)}.jsonl",
        "session_id": session_id,
        "channel": channel,
        "terminal_status": terminal_status,
        "has_error": has_error,
        "processed": processed,
        "created_at": "2026-06-16T00:00:00+00:00",
    }


class FakeBuildPlanAdapter:
    """Fake adapter that writes one wave plan file and captures briefs."""

    def __init__(self) -> None:
        self.dispatch_calls: list[dict[str, Any]] = []
        self.build_argv_calls: list[dict[str, Any]] = []

    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(backend="fake", available=True, detail="fake", streaming=False)

    def build_argv(self, brief: dict[str, object], worktree_path: Path) -> list[str]:
        self.build_argv_calls.append(dict(brief))
        return ["fake", f"node={brief.get('node_id')}", f"worktree_path={worktree_path}"]

    async def dispatch(  # type: ignore[override]
        self,
        brief: dict[str, object],
        *,
        worktree_path: Path,
        log_path: Path,
        timeout_s: int,
        log_header: dict[str, object] | None = None,
        on_event: Any = None,
    ) -> DispatchResult:
        self.dispatch_calls.append(dict(brief))
        out_dir = Path(str(brief["output_dir"]))
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "batch-wave-plan.md").write_text("generated\n", encoding="utf-8")
        return DispatchResult(
            outcome="done", result_text="ok", returncode=0, log_path=str(log_path)
        )


def _turn_bundle_day_slug(first_seen_at: str) -> str:
    return "160626" if first_seen_at.startswith("2026-06-16") else "150626"


def _setup_turn_bundles(tmp_path: Path, *, turns: list[dict[str, Any]]) -> Path:
    content_root = tmp_path / "content-root"
    content_root.mkdir(parents=True, exist_ok=True)
    (content_root / "sevn.json").write_text("{}", encoding="utf-8")
    bundles_dir = content_root / ".sevn" / "turns"
    bundles_dir.mkdir(parents=True, exist_ok=True)

    turns_by_day: dict[str, list[dict[str, Any]]] = {}
    for t in turns:
        created_at = t.get("created_at", "2026-06-16T00:00:00+00:00")
        day_slug = _turn_bundle_day_slug(created_at)
        turns_by_day.setdefault(day_slug, []).append({**t, "created_at": created_at})

    for day_slug, day_turns in turns_by_day.items():
        day_dir = bundles_dir / day_slug
        day_dir.mkdir(parents=True, exist_ok=True)
        turns_entries: list[dict[str, Any]] = []
        for t in day_turns:
            tid = t["turn_id"]
            session_id = t.get("session_id", "s1")
            channel = t.get("channel", "telegram")
            terminal_status = t["terminal_status"]
            file_name = f"{safe_turn_id(tid)}.jsonl"
            _write_bundle_jsonl(
                day_dir / file_name,
                turn_id=tid,
                session_id=session_id,
                channel=channel,
                terminal_status=terminal_status,
            )
            turns_entries.append(
                _bundle_index_entry(
                    turn_id=tid,
                    session_id=session_id,
                    channel=channel,
                    terminal_status=terminal_status,
                    processed=t.get("processed", False),
                    has_error=t.get("has_error", False),
                )
            )
        index_path = day_dir / "index.json"
        index_path.write_text(
            json.dumps({"version": 1, "turns": turns_entries}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return bundles_dir


def test_processes_all_unprocessed_turns_and_flips_processed(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """W5.1/W5.2: evaluates processed==false turns, flips processed for both clean+error."""
    error_tid = "telegram:user=1:session=abc:msg=deadbeef"
    clean_tid = "telegram:user=1:session=abc:msg=cafebabe"
    processed_true_tid = "telegram:user=2:session=xyz:msg=feedface"

    bundles_dir = _setup_turn_bundles(
        tmp_path,
        turns=[
            {"turn_id": clean_tid, "terminal_status": "ok", "processed": False, "has_error": False},
            {
                "turn_id": error_tid,
                "terminal_status": "error",
                "processed": False,
                "has_error": False,
            },
            {
                "turn_id": processed_true_tid,
                "terminal_status": "ok",
                "processed": True,
                "has_error": False,
            },
        ],
    )
    # Corrupt only the processed==true bundle so the driver must not touch it.
    (bundles_dir / "160626" / f"{safe_turn_id(processed_true_tid)}.jsonl").write_text(
        "INVALID\n", encoding="utf-8"
    )

    adapter = FakeBuildPlanAdapter()
    monkeypatch.setattr(driver, "get_adapter", lambda _b, *, options=None: adapter)
    monkeypatch.setattr(driver, "make_run_id", lambda _src: "testrun")

    out_dir = Path(__file__).resolve().parents[1] / "runs" / "input" / "from-errors-testrun"
    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()

    rc = driver.main(["--folder", str(bundles_dir)])
    assert rc == 0

    idx = json.loads((bundles_dir / "160626" / "index.json").read_text(encoding="utf-8"))
    turns_by_id = {t["turn_id"]: t for t in idx["turns"]}

    assert turns_by_id[clean_tid]["processed"] is True
    assert turns_by_id[clean_tid]["has_error"] is False
    assert turns_by_id[error_tid]["processed"] is True
    assert turns_by_id[error_tid]["has_error"] is True

    # Not selected; untouched.
    assert turns_by_id[processed_true_tid]["processed"] is True
    assert turns_by_id[processed_true_tid]["has_error"] is False

    assert len(adapter.dispatch_calls) == 1
    assert (out_dir / "batch-wave-plan.md").exists()

    # Cleanup.
    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()


def test_no_plan_when_all_clean(tmp_path: Path, monkeypatch: Any) -> None:
    """W5.1/W5.4: when there are no error turns, dispatch is skipped."""
    clean_tid = "telegram:user=1:session=abc:msg=cafebabe"
    bundles_dir = _setup_turn_bundles(
        tmp_path,
        turns=[
            {"turn_id": clean_tid, "terminal_status": "ok", "processed": False, "has_error": False}
        ],
    )

    adapter = FakeBuildPlanAdapter()
    monkeypatch.setattr(driver, "get_adapter", lambda _b, *, options=None: adapter)
    monkeypatch.setattr(driver, "make_run_id", lambda _src: "testrun-clean")

    out_dir = Path(__file__).resolve().parents[1] / "runs" / "input" / "from-errors-testrun-clean"
    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()

    rc = driver.main(["--folder", str(bundles_dir)])
    assert rc == 0
    assert adapter.dispatch_calls == []

    idx = json.loads((bundles_dir / "160626" / "index.json").read_text(encoding="utf-8"))
    assert idx["turns"][0]["processed"] is True
    assert idx["turns"][0]["has_error"] is False

    assert not out_dir.exists()


def test_single_plan_output_and_prompt_contains_all_error_turn_ids(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """W5.4: one plan file and the prompt includes all error turn ids."""
    error_tid_1 = "telegram:user=1:session=abc:msg=deadbeef"
    error_tid_2 = "telegram:user=1:session=abc:msg=baadf00d"
    bundles_dir = _setup_turn_bundles(
        tmp_path,
        turns=[
            {
                "turn_id": error_tid_1,
                "terminal_status": "error",
                "processed": False,
                "has_error": False,
            },
            {
                "turn_id": error_tid_2,
                "terminal_status": "error",
                "processed": False,
                "has_error": False,
            },
        ],
    )

    adapter = FakeBuildPlanAdapter()
    monkeypatch.setattr(driver, "get_adapter", lambda _b, *, options=None: adapter)
    monkeypatch.setattr(driver, "make_run_id", lambda _src: "testrun-errors")

    out_dir = Path(__file__).resolve().parents[1] / "runs" / "input" / "from-errors-testrun-errors"
    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()

    rc = driver.main(["--folder", str(bundles_dir)])
    assert rc == 0
    assert len(adapter.dispatch_calls) == 1

    prompt = str(adapter.dispatch_calls[0]["plan_worktree_path"])
    assert error_tid_1 in prompt
    assert error_tid_2 in prompt

    plans = list(out_dir.glob("*-wave-plan.md"))
    assert len(plans) == 1

    # Cleanup.
    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()


def test_dry_run_prints_dispatch_argv_and_does_not_dispatch(
    tmp_path: Path, monkeypatch: Any, capsys: Any
) -> None:
    """W5.4: --dry-run prints argv and skips dispatch."""
    error_tid = "telegram:user=1:session=abc:msg=deadbeef"
    bundles_dir = _setup_turn_bundles(
        tmp_path,
        turns=[
            {
                "turn_id": error_tid,
                "terminal_status": "error",
                "processed": False,
                "has_error": False,
            }
        ],
    )

    adapter = FakeBuildPlanAdapter()
    monkeypatch.setattr(driver, "get_adapter", lambda _b, *, options=None: adapter)
    monkeypatch.setattr(driver, "make_run_id", lambda _src: "testrun-dry")

    out_dir = Path(__file__).resolve().parents[1] / "runs" / "input" / "from-errors-testrun-dry"
    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()

    rc = driver.main(["--dry-run", "--folder", str(bundles_dir)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "[dry-run argv]" in captured.out
    assert adapter.dispatch_calls == []

    idx = json.loads((bundles_dir / "160626" / "index.json").read_text(encoding="utf-8"))
    assert idx["turns"][0]["processed"] is False
    assert not out_dir.exists()


def test_empty_folder_noop(tmp_path: Path, monkeypatch: Any) -> None:
    """W5.4: missing index.json means no-op and no dispatch."""
    empty_dir = tmp_path / "empty-bundles"
    empty_dir.mkdir(parents=True, exist_ok=True)

    adapter = FakeBuildPlanAdapter()
    called = {"count": 0}

    def _fake_get_adapter(_b: str, *, options: Any | None = None) -> FakeBuildPlanAdapter:
        called["count"] += 1
        return adapter

    monkeypatch.setattr(driver, "get_adapter", _fake_get_adapter)
    monkeypatch.setattr(driver, "make_run_id", lambda _src: "testrun-empty")

    out_dir = Path(__file__).resolve().parents[1] / "runs" / "input" / "from-errors-testrun-empty"
    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()

    rc = driver.main(["--folder", str(empty_dir)])
    assert rc == 0
    assert called["count"] == 0
    assert adapter.dispatch_calls == []
    assert not out_dir.exists()


def test_makefile_dry_run_build_plan_from_errors_target() -> None:
    """Makefile dry-run target passes --dry-run to the driver."""
    makefile = Path(__file__).resolve().parents[1] / "Makefile"
    block = makefile.read_text(encoding="utf-8").split("dry-run-build-plan-from-errors:", 1)[1]
    recipe = block.split("\n\n", 1)[0]
    assert "--dry-run" in recipe
    assert "tripll.build_plan_from_errors" in recipe


def test_resolved_prompt_includes_problem_types_taxonomy() -> None:
    """Resolved prompt appends taxonomy template with all problem kind ids."""
    prompt = driver._resolved_prompt_text(
        run_id="test-run",
        bundles_dir=Path("/tmp/bundles"),
        content_root=Path("/tmp/content"),
        error_turn_ids=["telegram:user=1:session=abc:msg=deadbeef"],
        output_dir=Path("/tmp/out"),
    )
    assert "Turn problem taxonomy" in prompt
    assert "## Turn problem matrix" in prompt
    for kind_id in (
        "log_error",
        "log_warning",
        "trace_error",
        "no_answer",
        "wrong_answer",
        "wrong_tool_use",
        "triage_routing",
        "channel_delivery",
        "terminal_failure",
        "other",
    ):
        assert kind_id in prompt, f"missing problem kind {kind_id}"


def test_dispatch_prompt_references_problem_types(tmp_path: Path, monkeypatch: Any) -> None:
    """Live dispatch brief includes taxonomy content in assembled prompt."""
    error_tid = "telegram:user=1:session=abc:msg=deadbeef"
    bundles_dir = _setup_turn_bundles(
        tmp_path,
        turns=[
            {
                "turn_id": error_tid,
                "terminal_status": "error",
                "processed": False,
                "has_error": False,
            }
        ],
    )

    adapter = FakeBuildPlanAdapter()
    monkeypatch.setattr(driver, "get_adapter", lambda _b, *, options=None: adapter)
    monkeypatch.setattr(driver, "make_run_id", lambda _src: "testrun-taxonomy")

    out_dir = (
        Path(__file__).resolve().parents[1] / "runs" / "input" / "from-errors-testrun-taxonomy"
    )
    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()

    rc = driver.main(["--folder", str(bundles_dir)])
    assert rc == 0
    assert len(adapter.dispatch_calls) == 1

    prompt = str(adapter.dispatch_calls[0]["plan_worktree_path"])
    assert "wrong_tool_use" in prompt
    assert "no_answer" in prompt
    assert "Step 1b" in prompt or "Taxonomy checklist" in prompt

    if out_dir.exists():
        for p in out_dir.glob("*"):
            p.unlink(missing_ok=True)
        out_dir.rmdir()
