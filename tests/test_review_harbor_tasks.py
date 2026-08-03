"""Tests for Harbor review task generation (#64 W3)."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from tripll.bench.review_harbor import (
    baseline_issues_to_mergecraft_payload,
    emit_harbor_review_tasks,
    harbor_task_slug,
)
from tripll.github.findings import load_baseline_issues


def _write_baseline(path: Path, records: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "\n".join(json.dumps(record, sort_keys=True) for record in records)
    path.write_text(payload + "\n", encoding="utf-8")


def _make_bundle(repo_dir: Path, bundle_path: Path) -> str:
    bundle_path.parent.mkdir(parents=True, exist_ok=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir, text=True).strip()
    subprocess.check_call(
        ["git", "bundle", "create", str(bundle_path), "HEAD"],
        cwd=repo_dir,
    )
    return head


@pytest.fixture
def sample_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "sample-repo"
    repo.mkdir()
    subprocess.check_call(["git", "init", "-b", "main"], cwd=repo)
    subprocess.check_call(["git", "config", "user.email", "bench@example.com"], cwd=repo)
    subprocess.check_call(["git", "config", "user.name", "Bench"], cwd=repo)
    (repo / "src").mkdir()
    (repo / "src" / "demo.py").write_text(
        "def run(items):\n    return items[0]\n", encoding="utf-8"
    )
    subprocess.check_call(["git", "add", "."], cwd=repo)
    subprocess.check_call(["git", "commit", "-m", "seed"], cwd=repo)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    return repo, head


def test_harbor_task_slug() -> None:
    assert harbor_task_slug("sevn-bot/tripll", 64) == "tripll-pr64"


def test_baseline_payload_is_deterministic() -> None:
    issues = [
        {
            "id": "tripll-pr64-02",
            "repo": "sevn-bot/tripll",
            "pr": 64,
            "head_sha": "abc",
            "path": "src/b.py",
            "line_range": [2, 2],
            "title": "Second",
            "description": "desc b",
            "provenance": "human",
        },
        {
            "id": "tripll-pr64-01",
            "repo": "sevn-bot/tripll",
            "pr": 64,
            "head_sha": "abc",
            "path": "src/a.py",
            "line_range": [1, 1],
            "title": "First",
            "description": "desc a",
            "provenance": "human",
        },
    ]
    first = json.dumps(baseline_issues_to_mergecraft_payload(issues), sort_keys=True)
    second = json.dumps(
        baseline_issues_to_mergecraft_payload(list(reversed(issues))), sort_keys=True
    )
    assert first == second
    payload = json.loads(first)
    assert len(payload["findings"]) == 2
    assert payload["findings"][0]["cluster_id"] == "tripll-pr64-01"


def test_emit_harbor_review_tasks_writes_required_files(
    tmp_path: Path,
    sample_repo: tuple[Path, str],
) -> None:
    _, head_sha = sample_repo
    baseline = tmp_path / "baseline.jsonl"
    _write_baseline(
        baseline,
        [
            {
                "id": "tripll-pr64-01",
                "repo": "sevn-bot/tripll",
                "pr": 64,
                "head_sha": head_sha,
                "path": "src/demo.py",
                "line_range": [1, 1],
                "category": "Functional Correctness",
                "severity": "high",
                "title": "Empty input crashes",
                "description": "Indexing items[0] without a guard fails on empty lists.",
                "provenance": "human",
                "requires_context_outside_diff": False,
            }
        ],
    )
    bundles_dir = tmp_path / "bundles"
    slug = harbor_task_slug("sevn-bot/tripll", 64)
    bundle_path = bundles_dir / f"{slug}.bundle"
    _make_bundle(sample_repo[0], bundle_path)

    dest_root = tmp_path / "review"
    emitted = emit_harbor_review_tasks(
        baseline,
        dest_root,
        bundles_dir=bundles_dir,
    )
    assert len(emitted) == 1
    task_dir = dest_root / slug
    for rel in (
        "task.toml",
        "instruction.md",
        "environment/Dockerfile",
        "environment/repo.bundle",
        "environment/pr_metadata.json",
        "solution/solve.sh",
        "solution/golden_findings.json",
        "tests/test.sh",
        "tests/expected_findings.json",
        "tests/verify_findings.py",
    ):
        assert (task_dir / rel).is_file(), rel

    task_toml = (task_dir / "task.toml").read_text(encoding="utf-8")
    assert 'network_mode = "no-network"' in task_toml
    assert f'head_sha = "{head_sha}"' in task_toml

    dockerfile = (task_dir / "environment/Dockerfile").read_text(encoding="utf-8")
    assert f"git checkout {head_sha}" in dockerfile
    assert "git clone /tmp/repo.bundle repo" in dockerfile


def test_solve_sh_emits_baseline_findings_and_scores(
    tmp_path: Path,
    sample_repo: tuple[Path, str],
) -> None:
    _, head_sha = sample_repo
    baseline = tmp_path / "baseline.jsonl"
    _write_baseline(
        baseline,
        [
            {
                "id": "tripll-pr64-01",
                "repo": "sevn-bot/tripll",
                "pr": 64,
                "head_sha": head_sha,
                "path": "src/demo.py",
                "line_range": [1, 1],
                "category": "Functional Correctness",
                "severity": "high",
                "title": "Empty input crashes",
                "description": "Indexing items[0] without a guard fails on empty lists.",
                "provenance": "human",
                "requires_context_outside_diff": False,
            }
        ],
    )
    bundles_dir = tmp_path / "bundles"
    slug = harbor_task_slug("sevn-bot/tripll", 64)
    bundle_path = bundles_dir / f"{slug}.bundle"
    _make_bundle(sample_repo[0], bundle_path)
    dest_root = tmp_path / "review"
    emit_harbor_review_tasks(baseline, dest_root, bundles_dir=bundles_dir)
    task_dir = dest_root / slug

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    findings_path = workspace / "findings.json"
    env = os.environ.copy()
    env["AGENT_FINDINGS_PATH"] = str(findings_path)
    subprocess.check_call(["bash", str(task_dir / "solution/solve.sh")], env=env)

    verify = subprocess.run(
        [
            "python3",
            str(task_dir / "tests/verify_findings.py"),
            str(findings_path),
            str(task_dir / "tests/expected_findings.json"),
        ],
        check=False,
    )
    assert verify.returncode == 0


def test_emit_is_deterministic_for_same_baseline(
    tmp_path: Path,
    sample_repo: tuple[Path, str],
) -> None:
    _, head_sha = sample_repo
    baseline = tmp_path / "baseline.jsonl"
    _write_baseline(
        baseline,
        [
            {
                "id": "tripll-pr64-01",
                "repo": "sevn-bot/tripll",
                "pr": 64,
                "head_sha": head_sha,
                "path": "src/demo.py",
                "line_range": [1, 1],
                "title": "Issue",
                "description": "Details",
                "provenance": "human",
            }
        ],
    )
    bundles_dir = tmp_path / "bundles"
    slug = harbor_task_slug("sevn-bot/tripll", 64)
    _make_bundle(sample_repo[0], bundles_dir / f"{slug}.bundle")

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    emit_harbor_review_tasks(baseline, first_root, bundles_dir=bundles_dir)
    emit_harbor_review_tasks(baseline, second_root, bundles_dir=bundles_dir)

    def _tree_bytes(root: Path) -> dict[str, bytes]:
        files: dict[str, bytes] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != "repo.bundle":
                files[str(path.relative_to(root))] = path.read_bytes()
        return files

    assert _tree_bytes(first_root / slug) == _tree_bytes(second_root / slug)


def test_emit_refuses_overwrite_without_force(
    tmp_path: Path,
    sample_repo: tuple[Path, str],
) -> None:
    _, head_sha = sample_repo
    baseline = tmp_path / "baseline.jsonl"
    _write_baseline(
        baseline,
        [
            {
                "id": "tripll-pr64-01",
                "repo": "sevn-bot/tripll",
                "pr": 64,
                "head_sha": head_sha,
                "path": "src/demo.py",
                "line_range": [1, 1],
                "title": "Issue",
                "description": "Details",
                "provenance": "human",
            }
        ],
    )
    bundles_dir = tmp_path / "bundles"
    slug = harbor_task_slug("sevn-bot/tripll", 64)
    _make_bundle(sample_repo[0], bundles_dir / f"{slug}.bundle")
    dest_root = tmp_path / "review"
    emit_harbor_review_tasks(baseline, dest_root, bundles_dir=bundles_dir)
    with pytest.raises(FileExistsError):
        emit_harbor_review_tasks(baseline, dest_root, bundles_dir=bundles_dir, force=False)


def test_fixture_baseline_round_trip() -> None:
    fixture = Path("tests/fixtures/review/baseline.jsonl")
    if not fixture.is_file():
        pytest.skip("fixture baseline missing")
    rows = load_baseline_issues(fixture)
    assert rows
    payload = baseline_issues_to_mergecraft_payload(rows)
    assert payload["findings"]
