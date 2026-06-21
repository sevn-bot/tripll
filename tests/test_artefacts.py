"""Tests for tripll.api._artefacts — safe log path resolver (D4 / W0.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tripll.api._artefacts import (
    LOG_FILENAME_RE,
    MAX_LOG_TAIL_BYTES,
    LogPathError,
    build_batch_timeline,
    parse_escalation_reasons,
    read_log_file_from_offset,
    read_pause_banners,
    render_report_markdown,
    resolve_attempt_log_path,
    sanitize_node_id_for_log,
    tail_log_file,
)
from tripll.pipeline import RunsRoot


@pytest.fixture
def rr(tmp_path: Path) -> RunsRoot:
    root = RunsRoot(tmp_path / "runs")
    root.init()
    return root


def test_sanitize_node_id_for_log() -> None:
    assert sanitize_node_id_for_log("telemetry:W0->Final") == "telemetry_W0-Final"


def test_log_filename_regex() -> None:
    assert LOG_FILENAME_RE.match("p_W1-attempt2.log")
    assert LOG_FILENAME_RE.match("telemetry_W0-Final-attempt1.log")
    assert not LOG_FILENAME_RE.match("bad.log")


def test_max_tail_bytes_is_200_kib() -> None:
    assert MAX_LOG_TAIL_BYTES == 200 * 1024


def test_resolve_attempt_log_path_happy(rr: RunsRoot) -> None:
    run_dir = rr.processing_dir / "r1"
    logs = run_dir / "logs"
    logs.mkdir(parents=True)
    log = logs / "p_W1-attempt1.log"
    log.write_text("line\n", encoding="utf-8")

    resolved = resolve_attempt_log_path(rr, "r1", "p:W1", 1)
    assert resolved == log.resolve()
    assert resolved.read_text(encoding="utf-8") == "line\n"


def test_resolve_attempt_log_path_processed_folder(rr: RunsRoot) -> None:
    run_dir = rr.processed_dir / "r2"
    logs = run_dir / "logs"
    logs.mkdir(parents=True)
    (logs / "core_W1-attempt1.log").write_text("ok", encoding="utf-8")

    resolved = resolve_attempt_log_path(rr, "r2", "core:W1", 1)
    assert resolved.name == "core_W1-attempt1.log"


def test_resolve_attempt_log_path_missing_run(rr: RunsRoot) -> None:
    with pytest.raises(LogPathError, match="Run not found"):
        resolve_attempt_log_path(rr, "missing", "p:W1", 1)


def test_resolve_attempt_log_path_missing_file(rr: RunsRoot) -> None:
    (rr.processing_dir / "r1" / "logs").mkdir(parents=True)
    with pytest.raises(LogPathError, match="Log file not found"):
        resolve_attempt_log_path(rr, "r1", "p:W1", 1)


def test_resolve_attempt_log_path_rejects_symlink(rr: RunsRoot, tmp_path: Path) -> None:
    run_dir = rr.processing_dir / "r1"
    logs = run_dir / "logs"
    logs.mkdir(parents=True)
    outside = tmp_path / "secret.log"
    outside.write_text("secret", encoding="utf-8")
    link = logs / "p_W1-attempt1.log"
    link.symlink_to(outside)

    with pytest.raises(LogPathError, match="symlink"):
        resolve_attempt_log_path(rr, "r1", "p:W1", 1)


def test_resolve_attempt_log_path_invalid_attempt(rr: RunsRoot) -> None:
    with pytest.raises(LogPathError, match="attempt_n"):
        resolve_attempt_log_path(rr, "r1", "p:W1", 0)


def test_tail_log_file_redacts_signature(tmp_path: Path) -> None:
    from tripll.log_redact import load_hide_keys

    log = tmp_path / "attempt1.log"
    log.write_text('{"type":"thinking","signature":"EtUOCmMIDhgCKkDeYY"}\n', encoding="utf-8")
    text, truncated = tail_log_file(log)
    assert "[redacted]" in text
    assert "EtUOCmMIDhgCKkDeYY" not in text
    assert truncated is False
    _ = load_hide_keys()


def test_tail_log_file_reads_content(tmp_path: Path) -> None:
    log = tmp_path / "sample.log"
    log.write_text("alpha\nbeta\n", encoding="utf-8")
    text, truncated = tail_log_file(log)
    assert "beta" in text
    assert truncated is False


def test_tail_log_file_truncates_large_file(tmp_path: Path) -> None:
    log = tmp_path / "big.log"
    log.write_bytes(b"x" * 500 + b"\n" + b"tail-line\n")
    text, truncated = tail_log_file(log, max_bytes=100)
    assert truncated is True
    assert "tail-line" in text


def test_read_log_file_from_offset_appends(tmp_path: Path) -> None:
    log = tmp_path / "grow.log"
    log.write_text("line1\n", encoding="utf-8")
    text, offset, truncated = read_log_file_from_offset(log, 0)
    assert text == "line1\n"
    assert offset == len(b"line1\n")
    assert truncated is False
    with log.open("a", encoding="utf-8") as fh:
        fh.write("line2\n")
    more, new_offset, truncated2 = read_log_file_from_offset(log, offset)
    assert more == "line2\n"
    assert new_offset > offset
    assert truncated2 is False


def test_read_pause_banners_quota(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "quota-paused.md").write_text("quota hit\n", encoding="utf-8")
    banners = read_pause_banners(run_dir)
    assert len(banners) == 1
    assert banners[0].kind == "quota"
    assert banners[0].snippet == "quota hit"


def test_build_batch_timeline_from_graph_json(tmp_path: Path) -> None:
    import json

    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    graph = {
        "batches": [{"batch_id": "A", "label": "first", "wave_ids": ["W1"]}],
        "nodes": {"p:W1": {"wave_id": "W1"}},
    }
    (run_dir / "graph.json").write_text(json.dumps(graph), encoding="utf-8")
    data = build_batch_timeline(run_dir, latest={}, ledger_node_ids=["p:W1"])
    assert data.source == "graph.json"
    assert data.lanes[0].batch_id == "A"
    assert data.lanes[0].nodes[0].node_id == "p:W1"


def test_render_report_markdown_headings_and_lists() -> None:
    html = render_report_markdown("# Title\n\n- **bold** item\n")
    assert "<h1>" in html
    assert "<ul>" in html
    assert "<strong>bold</strong>" in html


def test_parse_escalation_reasons(tmp_path: Path) -> None:
    run_dir = tmp_path / "failed-run"
    run_dir.mkdir()
    run_dir.joinpath("escalation.md").write_text(
        "# Escalation — failed-run\n\n"
        "Blocked waves (5 attempts exhausted):\n\n"
        "- p:R1 (1 attempts): no-progress escalation after 1 dispatch(es)\n"
        "- p:R2 (0 attempts): dependency deadlock — 1 node(s) undrained\n",
        encoding="utf-8",
    )
    reasons = parse_escalation_reasons(run_dir)
    assert reasons["p:R1"].startswith("no-progress escalation")
    assert reasons["p:R2"].startswith("dependency deadlock")
    assert parse_escalation_reasons(None) == {}
