# W0.4 — Backend invocation inventory

**Date:** 2026-06-15
**Scope:** W0 design-only; no implementation. Inventory of agent dispatch surfaces for W4 adapters.

---

## 1. claude_code adapter — Claude Code CLI (D1 default backend)

### Invocation pattern

From `src/sevn/data/bundled_skills/core/last30days/scripts/compare.sh`:

```bash
claude -p \
  --output-format stream-json \
  --verbose \
  --dangerously-skip-permissions \
  --add-dir <extra-dir> \
  "<prompt text or @prompt-file>"
```

### Flags relevant to tripll

| Flag | Purpose | tripll default |
|------|---------|-----------------|
| `-p` / `--print` | Non-interactive headless mode | always set |
| `--output-format stream-json` | JSON stream per event (tool use, text, result) | always set |
| `--verbose` | Emit tool-use events | always set |
| `--agent <agent-slug>` | Custom agent rules (e.g. `wave-plan-executor`, `wave-runner`) | set per brief |
| `--add-dir <path>` | Expose a worktree to the agent filesystem | set to worktree path |
| `--permission-mode acceptEdits` | Auto-accept edits in the worktree | default |
| `--dangerously-skip-permissions` | Full permissions opt-in (operator must enable in config) | behind `skip_permissions: true` config flag |

### Stream-JSON event types (W4 must parse)

```json
{"type": "system", "subtype": "init", ...}
{"type": "assistant", "message": {"content": [{"type": "text", "text": "…"}, {"type": "tool_use", …}]}, ...}
{"type": "user", "message": {"content": [{"type": "tool_result", …}]}, ...}
{"type": "result", "subtype": "success", "result": "...", "cost_usd": 0.12, ...}
{"type": "result", "subtype": "error_during_execution", "error": "...", ...}
```

W4 completion detection: `type == "result"` with `subtype in {"success", "error_during_execution"}`.

### Availability check

```python
import shutil
def claude_code_available() -> bool:
    return shutil.which("claude") is not None
```

### Wall-clock timeout

Wrap subprocess in `asyncio.wait_for(proc.communicate(), timeout=wall_clock_limit_s)`.
Pattern from: `src/sevn/tools/process.py` (`BackgroundJob`, `_read_stream`).

### Log capture

Stream stdout → `runs/<run-id>/logs/<node-id>-attempt<N>.log` line by line while running.
Pattern from: `src/sevn/ui/dashboard/api/cli_console.py` (`asyncio.create_subprocess_exec` + `communicate`).

---

## 2. cursor_local adapter — Cursor Agent CLI

### Status

Capability-gated on ``agent`` or ``cursor-agent`` on PATH (see
:func:`tripll.adapters.cursor_local.resolve_cursor_cli`).

### Invocation pattern (W4 — implemented)

```bash
agent \
  --print \
  --output-format stream-json \
  --workspace <worktree-path> \
  --trust \
  --model auto \
  "<prompt text>"
```

Subagent slugs (e.g. ``wave-runner``) are **not** a Cursor CLI flag — they are
prefixed in the prompt (``Use the wave-runner subagent workflow.``).  Scoped
paths from ``workspace_scope`` must live under the worktree root passed to
``--workspace`` (there is no ``--add-dir`` on ``agent``).

### Flags relevant to tripll

| Flag | Purpose | tripll default |
|------|---------|-----------------|
| `--print` | Non-interactive headless mode | always set |
| `--output-format stream-json` | JSON stream per event | always set |
| `--workspace <path>` | Primary workspace root | worktree path (includes scoped subdirs) |
| `--trust` | Trust workspace without prompt | always set |
| `--model <id>` | Model tier (`auto`, `composer-*`, …) | `auto` when orchestrator MODEL POLICY = auto; omitted when inherit (D11) |

Subagent selection: prompt prefix only (no ``--agent`` flag on ``agent`` CLI).

### Orchestrator-mode defaults (W4.2, D9, D11)

:func:`tripll.adapters.build_adapter` applies orchestrator config when present:

| Setting | Wave dispatch | Review-gate dispatch |
|---------|---------------|----------------------|
| Agent | ``wave-runner`` (``orchestrator.agent_wave``) | ``wave-orchestrator`` (``orchestrator.agent_orchestrator``) |
| Model (cursor_local) | ``auto`` or omitted per ``model_policy`` | same |
| Model (claude_code) | omitted (no silent opus/composer override) | omitted |

Default seeded profile ``cursor-local-executor`` uses ``agent=wave-runner``.

Headless gate dispatch: ``TRIPLL_ORCHESTRATOR_AGENT=1`` →
:func:`tripll.orchestrator_gate.dispatch_orchestrator_gate` after review-gate waves.

### Availability check

```python
from tripll.adapters.cursor_local import resolve_cursor_cli

def cursor_local_available() -> bool:
    return resolve_cursor_cli() is not None
```

If absent, ``dispatch()`` returns ``failed`` with:
> "Cursor CLI not installed — install `agent` to use this backend"

---

## 3. cursor_cloud adapter — Cursor Cloud / Cursor Background Agent

### Reused sevn primitives

Import path: `sevn.evolution.router` (under `tripll[cloud]` extra, D3).

| Primitive | Signature | Purpose |
|-----------|-----------|---------|
| `dispatch_cursor_cloud_implement` | `(conn, ws, layout, issue_id, *, session_key, poll, max_polls, poll_interval_sec) → EvolutionIssue` | Launch + optional poll; idempotent if agent already running |
| `launch_cursor_cloud_for_issue` | `(conn, ws, layout, issue_id, session_key) → EvolutionIssue` | Create cloud agent, persist cursor_agent_id |
| `poll_cursor_cloud_for_issue` | `(conn, ws, layout, issue_id) → EvolutionIssue` | Refresh status; mark done when terminal + pr_url set |
| `resolve_executor` | `(ws, kind) → 'local' | 'cursor_cloud'` | Route decision from config |
| `resolve_target_repo_url` | `(ws, workspace) → str` | GitHub/GitLab URL for cloud launch |

### Terminal statuses (from router.py)

```python
_CURSOR_TERMINAL_STATUSES = frozenset({
    "FINISHED", "FAILED", "CANCELLED", "CANCELLED_BY_USER", "ERROR", "DONE"
})
```

### Non-blocking poll loop

Pattern: `src/sevn/evolution/cursor_poll_scheduler.py` — background asyncio loop that calls `poll_cursor_cloud_for_issue` every N seconds until terminal.

W4 will adapt this into `AdapterProtocol.poll(attempt) -> Status` for the engine's async poll callbacks.

### Wave → Issue mapping

The cloud adapter must synthesize an `EvolutionIssue` from a `WaveNode` + `DispatchBrief`:

```python
issue = EvolutionIssue(
    id=f"wave-{node_id}",
    title=f"Wave {wave_id}: {plan_id}",
    kind="feature",
    body=brief_json_str,   # full JSON dispatch brief as issue body
    # …
)
```

### Availability check

```python
def cursor_cloud_available() -> bool:
    try:
        from sevn.evolution.router import dispatch_cursor_cloud_implement  # noqa: F401
        return True
    except ImportError:
        return False
```

---

## 4. Adapter protocol (W4 spec preview)

```python
from typing import Protocol
from dataclasses import dataclass
from enum import Enum

class AttemptOutcome(str, Enum):
    DONE = "done"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    SCOPE_BREACH = "scope_breach"

@dataclass
class Attempt:
    attempt_id: str
    node_id: str
    attempt_n: int
    backend: str
    log_path: str
    outcome: AttemptOutcome | None = None
    evidence: str = ""

class AgentAdapter(Protocol):
    """Pluggable backend for dispatching a wave brief to a real agent."""

    def capabilities(self) -> dict[str, bool]:
        """Return {available: bool, headless: bool, cloud: bool}."""
        ...

    async def dispatch(self, brief: dict, worktree: str) -> Attempt:
        """Send brief to agent; return Attempt with log_path set."""
        ...

    async def poll(self, attempt: Attempt) -> AttemptOutcome:
        """Check status; return outcome when terminal, else RUNNING sentinel."""
        ...
```

---

## 5. Comparison table

| Property | claude_code | cursor_local | cursor_cloud |
|----------|-------------|--------------|--------------|
| Install required | `claude` CLI | `cursor-agent` CLI | sevn `[cloud]` extra |
| Availability now | ✅ installed | ❌ not installed | ✅ (via sevn) |
| Subprocess model | async + stream | async + stream | HTTP poll loop |
| Log capture | stream-json stdout | stdout/stderr | API response |
| Wall-clock limit | asyncio timeout | asyncio timeout | poll max_polls × interval |
| Worktree support | `--add-dir` | `--workspace` | branch model |
| Default in tripll | ✅ yes | ❌ capability-gated | ❌ `[cloud]` extra |
| Commit during run | NEVER | NEVER | NEVER |
| `make ci-resume` during run | NEVER (only `ci-affected` / `ci-changed`) | NEVER | NEVER |

---

## 6. Deferred / manual smoke (W0 scope limit)

- **cursor-agent install:** adapter behind `command -v cursor-agent` gate; W4 will unit-test the gate.
- **Live claude CLI dispatch:** W4 will test arg-builder only; live dispatch is a manual operator smoke.
- **Live Cursor Cloud dispatch:** requires a workspace with Cursor Cloud configured; deferred to W4 integration test notes.
- **sevn.evolution.router import in cloud adapter:** requires `tripll[cloud]` extra; W4 wires the optional dependency.
