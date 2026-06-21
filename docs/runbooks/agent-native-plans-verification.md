# Agent-Native Plans — local Docker verification (Phase 5)

**Date:** 2026-06-17
**Branch:** `feature/tripll-agent-native-docker-local`
**Plan:** [`plan/tripll-agent-native-docker-local-wave-plan.md`](../../../plan/tripll-agent-native-docker-local-wave-plan.md) Phase 5
**Verifier:** wave-runner P5 gate (automated + operator spot-checks)

## Scope

Final verification gate for the Agent-Native Plans **localhost Docker sidecar** (D1–D8). Confirms the sidecar stack is healthy, MCP routes to `http://localhost:3000`, volume-backed SQLite survives restarts, and tripll `make check` remains green with no new monorepo CI deps.

Related runbooks: [localhost MCP (P3)](agent-native-plans-localhost-mcp.md), [host spike (P0)](agent-native-plans-spike.md), [operator hybrid loop (P4)](operator-runbook.md) §9.

---

## Phase 5 checklist results

| Check | Command / action | Result (2026-06-17) |
|-------|------------------|---------------------|
| Container healthy | `docker compose -f docker-compose.agent-native-plans.yml ps` | **Pass** — `agent-native-plans` **Up**, `0.0.0.0:3000->3000/tcp` |
| UI loads | Browser / curl `http://localhost:3000` | **Pass** — `GET /` → **200** (sign-in HTML); `GET /health` → **200** |
| Data survives restart | `stat /app/data/app.db` → restart → same inode | **Pass** — inode **1056797** unchanged; `/health` **200** post-restart |
| MCP from host | POST initialize with bearer to `/_agent-native/mcp` | **Pass** — `serverInfo.name` = `"Plan"`, protocol `2024-11-05`; no-auth → **401** |
| tripll unaffected | `make -C wave-orchestrator check` | **Pass** — 433 passed, 1 skipped (ruff, mypy, pytest) |
| No hosted leak (docs) | Grep committed runbooks for default hosted MCP | **Pass** — see §Hosted URL audit below |
| partial-ci (branch delta) | `SEVN_CI_BASE=origin/test-pre make partial-ci` | **Pass** — `wave-orchestrator-check` green |

### Operator follow-ups (manual, non-blocking for P5 commit)

| Check | Pass criterion | Status |
|-------|----------------|--------|
| `/visual-plan` via skill | New plan URL under `http://localhost:3000/plans/…` | **Operator** — run after MCP repoint (P3 §6 step 5) |
| Client MCP list | Localhost server enabled; hosted entry removed | **Operator** — confirm in Cursor / Claude Code settings |
| Agent logs during skill | No outbound `plan.agent-native.com` | **Operator** — optional network grep during `/visual-plan` |

Automated MCP handshake and volume persistence satisfy the plan’s infrastructure gate; skill/UI end-to-end is documented in [agent-native-plans-localhost-mcp.md](agent-native-plans-localhost-mcp.md) §5–§6.

---

## Commands run (evidence)

From repo root unless noted.

```bash
# Container
cd wave-orchestrator
docker compose -f docker-compose.agent-native-plans.yml ps

# Health / UI
curl -s -o /dev/null -w "health:%{http_code}\n" http://localhost:3000/health
curl -s -o /dev/null -w "root:%{http_code}\n" http://localhost:3000/

# MCP (bearer from .env.agent-native — never commit)
curl -s -o /dev/null -w "mcp_no_auth:%{http_code}\n" http://localhost:3000/_agent-native/mcp
curl -s -X POST http://localhost:3000/_agent-native/mcp \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"p5-verify","version":"1.0"}}}'

# Volume persistence
docker compose -f docker-compose.agent-native-plans.yml exec agent-native-plans stat -c '%i' /app/data/app.db
docker compose -f docker-compose.agent-native-plans.yml restart agent-native-plans
# inode unchanged; health 200

# tripll + CI
make -C wave-orchestrator check
SEVN_CI_BASE=origin/test-pre make partial-ci
```

**Observed MCP initialize excerpt:** `"serverInfo":{"name":"Plan","version":"1.0.0",...}`

---

## Hosted URL audit (no default leak)

Committed runbooks under `wave-orchestrator/docs/runbooks/`:

| File | `plan.agent-native.com` usage | Verdict |
|------|------------------------------|---------|
| `operator-runbook.md` §9 | None — `PLANS_BASE_URL=http://localhost:3000` only | OK — operator default is localhost |
| `agent-native-plans-localhost-mcp.md` | Mentions hosted URL only as **replace/remove** migration target | OK — documents anti-leak checklist |
| `agent-native-plans-spike.md` | Historical P0 row: hosted was default **before** Docker sidecar | OK — archived spike context, not operator path |

No committed runbook instructs operators to use hosted MCP as the default path after P2–P4.

---

## Branch commits (P0–P5)

| Phase | Commit | Subject |
|-------|--------|---------|
| P0 | `3641fe657` | `docs(tripll): Agent-Native Plans host spike (P0)` |
| P1 | `04ef9628b` | `chore(tripll): Agent-Native Plans Dockerfile scaffold (P1)` |
| P2 | `765105b84` | `feat(tripll): Agent-Native Plans docker-compose and make targets (P2)` |
| P3 | `a5a435ebd` | `docs(tripll): Agent-Native localhost MCP operator guide (P3)` |
| P4 | `c1b689a19` | `docs(tripll): hybrid Plans sidecar runbook (P4)` |
| P5 | *(this commit)* | `docs(tripll): Agent-Native Docker local verification (P5)` |

---

## WIP hygiene

Unrelated local edits (`engine.py`, `orchestrator_gate.py`, `test_adapters.py`) were **not** committed; prior stash `p4-temp-wip` retained on branch.

---

## References

- [Agent-Native Deployment — Docker](https://www.agent-native.com/docs/deployment#docker)
- [`docker-compose.agent-native-plans.yml`](../../docker-compose.agent-native-plans.yml)
- [`.env.agent-native.example`](../../.env.agent-native.example)
