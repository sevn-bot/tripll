"""Tests for tripll.wave_task — wave checklist parser (D6 / W0.5)."""

from __future__ import annotations

from pathlib import Path

from tripll.wave_task import infer_active_task, parse_wave_tasks

_FIXTURE = Path(__file__).parent / "fixtures" / "wave-plan-w0-slice.md"


def test_parse_wave_tasks_from_fixture() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    bullets = parse_wave_tasks(text)
    ids = [b.id for b in bullets]
    assert ids == ["W0.1", "W0.2", "W0.3", "W0.4"]
    assert bullets[0].checked is False
    assert bullets[3].checked is True


def test_parse_wave_tasks_r1_m1_ids() -> None:
    text = "- [ ] **R1.1** Capability probe\n- [ ] **M1.2** Viewer routes\n- [x] **Final** Ship\n"
    bullets = parse_wave_tasks(text)
    assert [b.id for b in bullets] == ["R1.1", "M1.2", "Final"]
    assert bullets[2].checked is True


def test_infer_active_task_longest_substring_match() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    result = infer_active_task(
        text,
        last_action="Lock latest_events_by_node ledger API shape",
        phase="running",
    )
    assert result.inferred_task_id == "W0.2"
    active = [b for b in result.bullets if b.active]
    assert len(active) == 1
    assert active[0].id == "W0.2"


def test_infer_active_task_running_fallback_first_unchecked() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    result = infer_active_task(text, last_action=None, phase="running")
    assert result.inferred_task_id == "W0.1"
    assert result.bullets[0].active is True


def test_infer_active_task_no_match_non_running() -> None:
    text = _FIXTURE.read_text(encoding="utf-8")
    result = infer_active_task(text, last_action="unrelated action", phase="done")
    assert result.inferred_task_id is None
    assert not any(b.active for b in result.bullets)
