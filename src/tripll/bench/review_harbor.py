"""Emit Harbor review tasks from frozen baseline JSONL (#64 W3).

Exports:
    harbor_task_slug — directory name ``{repo}-pr{N}`` for a curated PR.
    baseline_issues_to_mergecraft_payload — map baseline records to mergeCraft JSON.
    emit_harbor_review_tasks — write Harbor task trees under ``bench/review/``.
    render_harbor_task_files — render one task directory from grouped baseline issues.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — CLI paths at runtime
from typing import Any

from tripll.github.findings import load_baseline_issues

_AGENT_FINDINGS_PATH = "/workspace/findings.json"
_GENERATOR_VERSION = "tripll.bench.review_harbor.v1"

_SEVERITY_TO_MERGECRAFT = {
    "critical": "Critical",
    "high": "Major",
    "medium": "Minor",
    "low": "Trivial",
}

_VERIFY_FINDINGS_PY = '''\
"""Deterministic mergeCraft findings verifier for Harbor review tasks."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _normalize_finding(raw: dict[str, Any]) -> dict[str, Any]:
    start = int(raw.get("start_line") or 1)
    end = int(raw.get("end_line") or start)
    return {
        "category": str(raw.get("category") or ""),
        "confidence": str(raw.get("confidence") or ""),
        "end_line": end,
        "fingerprint": str(raw.get("fingerprint") or ""),
        "message": str(raw.get("message") or ""),
        "path": str(raw.get("path") or ""),
        "rule_id": str(raw.get("rule_id") or ""),
        "severity": str(raw.get("severity") or ""),
        "start_line": start,
        "tool": str(raw.get("tool") or ""),
    }


def _load_payload(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        msg = f"{path}: expected object envelope"
        raise ValueError(msg)
    findings = data.get("findings")
    if not isinstance(findings, list):
        msg = f"{path}: findings must be an array"
        raise ValueError(msg)
    return [_normalize_finding(item) for item in findings if isinstance(item, dict)]


def findings_match(actual_path: Path, expected_path: Path) -> bool:
    """Return True when both payloads contain identical normalized findings."""
    actual = sorted(_load_payload(actual_path), key=lambda row: row["fingerprint"])
    expected = sorted(_load_payload(expected_path), key=lambda row: row["fingerprint"])
    return actual == expected


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 2:
        sys.stderr.write("usage: verify_findings.py ACTUAL.json EXPECTED.json\\n")
        return 2
    actual_path = Path(args[0])
    expected_path = Path(args[1])
    if not actual_path.is_file():
        sys.stderr.write(f"missing findings: {actual_path}\\n")
        return 1
    if not expected_path.is_file():
        sys.stderr.write(f"missing expected: {expected_path}\\n")
        return 1
    if findings_match(actual_path, expected_path):
        return 0
    sys.stderr.write("findings mismatch\\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
'''


@dataclass(frozen=True, slots=True)
class HarborTaskSpec:
    """Grouped baseline issues for one curated pull request."""

    repo: str
    pr: int
    head_sha: str
    issues: tuple[dict[str, Any], ...]


def harbor_task_slug(repo: str, pr: int) -> str:
    """Build Harbor task directory name ``{repo_short}-pr{N}``."""
    repo_short = repo.rsplit("/", 1)[-1]
    return f"{repo_short}-pr{pr}"


def _baseline_fingerprint(issue_id: str) -> str:
    digest = hashlib.sha256(issue_id.encode("utf-8")).hexdigest()
    return digest[:24]


def baseline_issue_to_mergecraft_finding(issue: dict[str, Any]) -> dict[str, Any]:
    """Map one baseline JSONL record to a mergeCraft ``Finding`` object."""
    issue_id = str(issue.get("id") or "")
    path = str(issue.get("path") or "")
    line_range = issue.get("line_range") or [1, 1]
    start = int(line_range[0]) if line_range else 1
    end = int(line_range[1]) if len(line_range) > 1 else start
    severity_raw = str(issue.get("severity") or "medium").lower()
    severity = _SEVERITY_TO_MERGECRAFT.get(severity_raw, "Minor")
    title = str(issue.get("title") or "")
    description = str(issue.get("description") or title)
    message = title if title else description
    fingerprint = _baseline_fingerprint(issue_id)
    return {
        "tool": "agent",
        "rule_id": f"baseline:{issue_id}",
        "category": str(issue.get("category") or "Functional Correctness"),
        "severity": severity,
        "confidence": "certain",
        "message": message,
        "path": path,
        "start_line": start,
        "end_line": end,
        "fingerprint": fingerprint,
        "evidence": [description] if description else [],
        "remediation": description or None,
        "autofix": None,
        "introduced_by_pr": "true",
        "source": "baseline",
        "cluster_id": issue_id,
    }


def baseline_issues_to_mergecraft_payload(issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Convert baseline issues to deterministic mergeCraft ``{"findings": [...]}`` JSON."""
    ordered = sorted(issues, key=lambda row: str(row.get("id") or ""))
    findings = [baseline_issue_to_mergecraft_finding(issue) for issue in ordered]
    return {"findings": findings}


def _group_baseline_by_pr(records: list[dict[str, Any]]) -> list[HarborTaskSpec]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    head_shas: dict[tuple[str, int], str] = {}
    for record in records:
        repo = str(record.get("repo") or "")
        pr_raw = record.get("pr")
        if not repo or pr_raw is None:
            continue
        pr = int(pr_raw)
        key = (repo, pr)
        grouped[key].append(record)
        sha = str(record.get("head_sha") or "")
        if sha:
            head_shas[key] = sha
    specs: list[HarborTaskSpec] = []
    for (repo, pr), issues in sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1])):
        ordered_issues = tuple(sorted(issues, key=lambda row: str(row.get("id") or "")))
        specs.append(
            HarborTaskSpec(
                repo=repo,
                pr=pr,
                head_sha=head_shas.get((repo, pr), ""),
                issues=ordered_issues,
            )
        )
    return specs


def _render_task_toml(spec: HarborTaskSpec) -> str:
    slug = harbor_task_slug(spec.repo, spec.pr)
    return f'''\
schema_version = "1.4"

[task]
name = "tripll/review/{slug}"
version = "1.0.0"
description = "Frozen code review task for {spec.repo} PR #{spec.pr}"
keywords = ["review", "mergecraft", "benchmark"]

[metadata]
generator = "{_GENERATOR_VERSION}"
repo = "{spec.repo}"
pr = {spec.pr}
head_sha = "{spec.head_sha}"
baseline_issue_count = {len(spec.issues)}

[verifier]
timeout_sec = 120.0

[agent]
timeout_sec = 900.0

[environment]
network_mode = "no-network"
build_timeout_sec = 600.0
os = "linux"
cpus = 1
memory_mb = 2048
storage_mb = 4096
'''


def _render_instruction_md(spec: HarborTaskSpec) -> str:
    slug = harbor_task_slug(spec.repo, spec.pr)
    issue_lines = "\n".join(
        f"- `{issue.get('id')}` — {issue.get('title')}" for issue in spec.issues
    )
    return f"""\
# Review pull request #{spec.pr} ({spec.repo})

You are reviewing a **frozen** pull request for the tripll review benchmark (`{slug}`).

## Context

- Repository checkout: `/workspace/repo` (seeded at `{spec.head_sha}`; **no network**)
- PR metadata and diff: `/workspace/pr_metadata.json` (served from disk, not live GitHub)
- Baseline issue ids (ground truth labels, for orientation only): see task metadata

## Task

Perform a code review of the changes introduced by this pull request. Inspect the full
repository — callers, tests, and neighbouring implementations matter, not just the diff hunk.

Write your findings as mergeCraft structured JSON to **`{_AGENT_FINDINGS_PATH}`** using this
envelope:

```json
{{"findings": [/* mergeCraft Finding objects */]}}
```

Each finding must include at minimum: `tool`, `rule_id`, `category`, `severity`, `confidence`,
`message`, `path`, `start_line`, `end_line`, `fingerprint`, `evidence`, `remediation`, `autofix`,
`introduced_by_pr`, `source`, `cluster_id`.

## Baseline orientation (not exhaustive)

{issue_lines}
"""


def _render_pr_metadata(spec: HarborTaskSpec) -> dict[str, Any]:
    return {
        "repo": spec.repo,
        "pr": spec.pr,
        "head_sha": spec.head_sha,
        "title": f"Review benchmark task for PR #{spec.pr}",
        "base_ref": "origin/main",
        "issue_ids": [str(issue.get("id") or "") for issue in spec.issues],
        "issues": [
            {
                "id": issue.get("id"),
                "path": issue.get("path"),
                "line_range": issue.get("line_range"),
                "title": issue.get("title"),
                "provenance": issue.get("provenance"),
                "requires_context_outside_diff": issue.get("requires_context_outside_diff"),
            }
            for issue in spec.issues
        ],
    }


def _render_dockerfile(spec: HarborTaskSpec) -> str:
    checkout_ref = spec.head_sha or "HEAD"
    return f"""\
FROM ubuntu:22.04

RUN apt-get update \\
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \\
        ca-certificates git python3 python3-minimal \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY repo.bundle /tmp/repo.bundle
COPY pr_metadata.json /workspace/pr_metadata.json

RUN git clone /tmp/repo.bundle repo \\
    && cd repo \\
    && git checkout {checkout_ref}

ENV REVIEW_REPO=/workspace/repo
ENV PR_METADATA=/workspace/pr_metadata.json
ENV AGENT_FINDINGS_PATH={_AGENT_FINDINGS_PATH}
"""


def _render_solve_sh() -> str:
    return f"""\
#!/bin/bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${{BASH_SOURCE[0]}}")" && pwd)"
cp "${{SCRIPT_DIR}}/golden_findings.json" "${{AGENT_FINDINGS_PATH:-{_AGENT_FINDINGS_PATH}}}"
"""


def _render_test_sh() -> str:
    return f"""\
#!/bin/bash
set -euo pipefail
ACTUAL="${{AGENT_FINDINGS_PATH:-{_AGENT_FINDINGS_PATH}}}"
python3 /tests/verify_findings.py "$ACTUAL" /tests/expected_findings.json
if [ $? -eq 0 ]; then
  echo 1 > /logs/verifier/reward.txt
else
  echo 0 > /logs/verifier/reward.txt
fi
"""


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def render_harbor_task_files(
    spec: HarborTaskSpec,
    dest: Path,
    *,
    bundle_path: Path,
) -> None:
    """Write one Harbor task tree to *dest* from *spec* and a frozen git bundle."""
    if not bundle_path.is_file():
        msg = f"git bundle missing for {dest.name}: {bundle_path}"
        raise FileNotFoundError(msg)

    payload = baseline_issues_to_mergecraft_payload(list(spec.issues))
    expected_json = json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"

    dest.mkdir(parents=True, exist_ok=True)
    (dest / "task.toml").write_text(_render_task_toml(spec), encoding="utf-8")
    (dest / "instruction.md").write_text(_render_instruction_md(spec), encoding="utf-8")

    env_dir = dest / "environment"
    env_dir.mkdir(exist_ok=True)
    (env_dir / "Dockerfile").write_text(_render_dockerfile(spec), encoding="utf-8")
    shutil.copy2(bundle_path, env_dir / "repo.bundle")
    (env_dir / "pr_metadata.json").write_text(
        json.dumps(_render_pr_metadata(spec), sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    solution_dir = dest / "solution"
    solution_dir.mkdir(exist_ok=True)
    (solution_dir / "golden_findings.json").write_text(expected_json, encoding="utf-8")
    _write_executable(solution_dir / "solve.sh", _render_solve_sh())

    tests_dir = dest / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "expected_findings.json").write_text(expected_json, encoding="utf-8")
    (tests_dir / "verify_findings.py").write_text(_VERIFY_FINDINGS_PY, encoding="utf-8")
    _write_executable(tests_dir / "test.sh", _render_test_sh())


def emit_harbor_review_tasks(
    baseline_path: Path,
    dest_root: Path,
    *,
    bundles_dir: Path,
    force: bool = False,
) -> list[Path]:
    """Emit one Harbor task per curated PR from frozen baseline JSONL.

    Args:
        baseline_path: Review baseline JSONL (``bench/review/baseline.jsonl``).
        dest_root: Output root (typically ``bench/review/``).
        bundles_dir: Directory containing ``{slug}.bundle`` git bundles per PR task.
        force: When False, refuse to overwrite existing task directories.

    Returns:
        Paths to emitted Harbor task directories.

    Raises:
        FileNotFoundError: Missing baseline file or git bundle for a PR group.
        FileExistsError: Task directory exists and *force* is False.
    """
    if not baseline_path.is_file():
        msg = f"baseline not found: {baseline_path}"
        raise FileNotFoundError(msg)
    records = load_baseline_issues(baseline_path)
    if not records:
        return []

    emitted: list[Path] = []
    for spec in _group_baseline_by_pr(records):
        slug = harbor_task_slug(spec.repo, spec.pr)
        task_dir = dest_root / slug
        if task_dir.exists() and any(task_dir.iterdir()) and not force:
            msg = (
                f"Harbor task {task_dir} already exists; pass force=True for operator regeneration"
            )
            raise FileExistsError(msg)
        bundle_path = bundles_dir / f"{slug}.bundle"
        render_harbor_task_files(spec, task_dir, bundle_path=bundle_path)
        emitted.append(task_dir)
    return emitted


__all__ = [
    "HarborTaskSpec",
    "baseline_issue_to_mergecraft_finding",
    "baseline_issues_to_mergecraft_payload",
    "emit_harbor_review_tasks",
    "harbor_task_slug",
    "render_harbor_task_files",
]
