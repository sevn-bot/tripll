"""Tests for tripll.pipeline — folder lifecycle and run-id derivation."""

from __future__ import annotations

import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tripll.pipeline import RunsRoot, make_run_id

# ---------------------------------------------------------------------------
# make_run_id
# ---------------------------------------------------------------------------


def test_make_run_id_basic() -> None:
    ts = datetime(2026, 6, 15, 16, 0, 12, tzinfo=UTC)
    assert make_run_id("dev_eval_14062026", now=ts) == "dev-eval-14062026-20260615-160012"


def test_make_run_id_special_chars() -> None:
    ts = datetime(2026, 6, 15, 9, 3, 5, tzinfo=UTC)
    result = make_run_id("My Waves!", now=ts)
    assert result == "my-waves-20260615-090305"


def test_make_run_id_max_slug_length() -> None:
    ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=UTC)
    long_name = "a" * 50
    rid = make_run_id(long_name, now=ts)
    slug_part = rid.rsplit("-20260101-", 1)[0]
    assert len(slug_part) <= 32


def test_make_run_id_uses_utc_by_default() -> None:
    rid = make_run_id("test")
    # Should contain a valid timestamp segment
    parts = rid.rsplit("-", 2)
    assert len(parts) == 3
    assert len(parts[-1]) == 6  # HHMMSS
    assert len(parts[-2]) == 8  # YYYYMMDD


# ---------------------------------------------------------------------------
# RunsRoot.init
# ---------------------------------------------------------------------------


def test_init_creates_dirs() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        assert rr.input_dir.exists()
        assert rr.processing_dir.exists()
        assert rr.processed_dir.exists()
        assert rr.failed_dir.exists()


def test_init_idempotent() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        rr.init()  # second call must not raise
        assert rr.input_dir.exists()


# ---------------------------------------------------------------------------
# claim_input
# ---------------------------------------------------------------------------


def test_claim_input_moves_dir() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "my-wave-set"
        src.mkdir()
        (src / "parallel-wave.md").write_text("# test")

        rid = rr.claim_input(src, run_id="my-wave-set-20260615-160012")

        assert rid == "my-wave-set-20260615-160012"
        assert not src.exists()
        assert (rr.processing_dir / rid).exists()
        assert (rr.processing_dir / rid / "parallel-wave.md").exists()


def test_claim_input_auto_run_id() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "test-set"
        src.mkdir()

        rid = rr.claim_input(src)
        assert rid.startswith("test-set-")
        assert (rr.processing_dir / rid).exists()


def test_claim_input_missing_raises() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        with pytest.raises(FileNotFoundError):
            rr.claim_input(rr.input_dir / "no-such-dir")


def test_claim_input_duplicate_raises() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "my-set"
        src.mkdir()
        rr.claim_input(src, run_id="dup-run-id")

        # Try to claim again with same run_id (processing dir already exists)
        src2 = rr.input_dir / "my-set-2"
        src2.mkdir()
        with pytest.raises(FileExistsError):
            rr.claim_input(src2, run_id="dup-run-id")


# ---------------------------------------------------------------------------
# complete_run / fail_run
# ---------------------------------------------------------------------------


def test_complete_run_moves_to_processed() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "my-set"
        src.mkdir()
        rid = rr.claim_input(src, run_id="my-run-id")

        dest = rr.complete_run(rid)

        assert dest == rr.processed_dir / rid
        assert dest.exists()
        assert not (rr.processing_dir / rid).exists()


def test_fail_run_moves_to_failed() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "bad-set"
        src.mkdir()
        rid = rr.claim_input(src, run_id="bad-run-id")

        dest = rr.fail_run(rid)

        assert dest == rr.failed_dir / rid
        assert dest.exists()
        assert not (rr.processing_dir / rid).exists()


def test_complete_run_missing_raises() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        with pytest.raises(FileNotFoundError):
            rr.complete_run("no-such-run")


def test_fail_run_missing_raises() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        with pytest.raises(FileNotFoundError):
            rr.fail_run("no-such-run")


# ---------------------------------------------------------------------------
# Listing helpers
# ---------------------------------------------------------------------------


def test_list_input_empty() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        assert rr.list_input() == []


def test_list_input_returns_entries() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        (rr.input_dir / "set-a").mkdir()
        (rr.input_dir / "set-b").mkdir()
        names = [p.name for p in rr.list_input()]
        assert sorted(names) == ["set-a", "set-b"]


def test_list_input_ignores_dotfiles() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        (rr.input_dir / ".DS_Store").write_text("macos")
        (rr.input_dir / "real-set").mkdir()
        names = [p.name for p in rr.list_input()]
        assert names == ["real-set"]


def test_list_processing_after_claim() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "s"
        src.mkdir()
        rid = rr.claim_input(src, run_id="my-run-20260615-120000")
        assert rr.list_processing() == [rid]


def test_list_processed_after_complete() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "s"
        src.mkdir()
        rid = rr.claim_input(src, run_id="done-run-20260615-120000")
        rr.complete_run(rid)
        assert rr.list_processed() == [rid]
        assert rr.list_processing() == []


def test_list_failed_after_fail() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "s"
        src.mkdir()
        rid = rr.claim_input(src, run_id="fail-run-20260615-120000")
        rr.fail_run(rid)
        assert rr.list_failed() == [rid]
        assert rr.list_processing() == []


def test_delete_run_from_processing() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "s"
        src.mkdir()
        rid = rr.claim_input(src, run_id="del-run-20260615-120000")
        deleted = rr.delete_run(rid)
        assert deleted.name == rid
        assert rr.find_run_dir(rid) is None
        assert rr.list_processing() == []


def test_delete_run_not_found() -> None:
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        with pytest.raises(FileNotFoundError):
            rr.delete_run("missing-run")


def test_reset_run_retries_when_input_already_restored() -> None:
    """Partial reset (plans copied, run dir stuck) can be retried safely."""
    with tempfile.TemporaryDirectory() as d:
        rr = RunsRoot(Path(d) / "runs")
        rr.init()
        src = rr.input_dir / "my-set"
        src.mkdir()
        plan = src / "my-set-wave-plan.md"
        plan.write_text("# plan\n", encoding="utf-8")
        rid = rr.claim_input(src, run_id="my-set-20260618-120000")
        run_dir = rr.find_run_dir(rid)
        assert run_dir is not None
        dest = rr.input_dir / "my-set"
        dest.mkdir()
        shutil.copy2(run_dir / "my-set-wave-plan.md", dest / "my-set-wave-plan.md")
        for child in list(run_dir.iterdir()):
            if child.name == "ledger.db":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        restored = rr.reset_run(rid)
        assert restored == dest
        assert rr.find_run_dir(rid) is None
        assert (dest / "my-set-wave-plan.md").is_file()
