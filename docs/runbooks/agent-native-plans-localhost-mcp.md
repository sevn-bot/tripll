# Agent-Native Plans — localhost MCP operator guide (Phase 3)

**Date:** 2026-06-17
**Branch:** `feature/tripll-agent-native-docker-local`
**Plan:** [`plan/tripll-agent-native-docker-local-wave-plan.md`](../../../plan/tripll-agent-native-docker-local-wave-plan.md) Phase 3 only
**Prerequisites:** Phase 2 done — `make plans-up` serves Plans on `:3000`; `.env.agent-native` populated from [`.env.agent-native.example`](../../.env.agent-native.example) (D7).

## Purpose

Repoint coding-agent MCP from hosted `https://plan.agent-native.com/_agent-native/mcp` to the **local Docker sidecar** at `http://localhost:3000/_agent-native/mcp` (D5), using `ACCESS_TOKEN` bearer auth (D4). After this step, `/visual-plan` and `/visual-recap` skills create plans in the operator's volume-backed SQLite — no calls to `plan.agent-native.com`.

Phase 0 host spike notes remain in [`agent-native-plans-spike.md`](agent-native-plans-spike.md). Phase 4 (tripll runbook links) is separate.

---

## 1. Start the sidecar

From `wave-orchestrator/`:

```bash
cp .env.agent-native.example .env.agent-native   # once — fill every REPLACE_* secret
# openssl rand -hex 32   # repeat for each secret + ACCESS_TOKEN

make plans-up
docker compose -f docker-compose.agent-native-plans.yml ps   # STATUS: Up, PORT 0.0.0.0:3000->3000
```

Container data path (D2): named volume `wave-orchestrator_agent-native-plans-data` → `/app/data/app.db` inside the container.

---

## 2. Repoint MCP to localhost

### Option A — CLI connect (recommended)

Run in an **interactive** terminal (writes client MCP config; idempotent):

```bash
npx @agent-native/core@latest connect http://localhost:3000 --client all
```

When prompted for auth, use the **no-browser token path** (matches local single-tenant D4):

```bash
npx @agent-native/core@latest connect http://localhost:3000 \
  --client all \
  --token "$(grep '^ACCESS_TOKEN=' wave-orchestrator/.env.agent-native | cut -d= -f2-)"
```

Replace the `grep` with your token value if you prefer not to shell-read `.env.agent-native`. **Never commit** `.env.agent-native` or paste the token into tracked files.

Supported clients (2026-06-17 CLI): `claude-code`, `claude-code-cli`, `codex`, `cursor` (when listed by picker). Restart or reload each client after connect so MCP tools appear.

### Option B — Manual MCP entry

| Field | Value |
|-------|--------|
| **URL** | `http://localhost:3000/_agent-native/mcp` |
| **Header** | `Authorization: Bearer <ACCESS_TOKEN>` |

Example shape (Cursor / Claude Code remote MCP JSON — exact path varies by client):

```json
{
  "mcpServers": {
    "agent-native-plans-local": {
      "url": "http://localhost:3000/_agent-native/mcp",
      "headers": {
        "Authorization": "Bearer YOUR_ACCESS_TOKEN"
      }
    }
  }
}
```

Use the same `ACCESS_TOKEN` value as in `.env.agent-native`. Hosted URL `https://plan.agent-native.com/_agent-native/mcp` should be **removed or disabled** so skills do not leak to SaaS (Phase 5 checklist).

---

## 3. Verify container health (curl)

Run from the host while `make plans-up` is active:

```bash
# Primary — Nitro responds HTTP 200 when the process is up (body may be sign-in HTML)
curl -s -o /dev/null -w "health: %{http_code}\n" http://localhost:3000/health

# Fallback — JSON 404 on bare / is normal for this scaffold
curl -sI http://localhost:3000/ | head -5
```

**Observed (2026-06-17, Docker `:3000`):**

| Check | Result |
|-------|--------|
| `GET /health` | **HTTP 200** — server up |
| `HEAD /` | **HTTP 404** — JSON not-found (expected) |
| `GET /api/health` (no auth) | **HTTP 401** — API layer requires session/token |

---

## 4. Verify MCP endpoint (curl)

MCP uses **POST** with JSON-RPC and requires the bearer token when `ACCESS_TOKEN` is set.

### 4a. Without auth — expect rejection

```bash
curl -s -o /dev/null -w "mcp_no_auth: %{http_code}\n" \
  http://localhost:3000/_agent-native/mcp
# Expected: 401
```

### 4b. With bearer — initialize handshake

Substitute your token (same as `.env.agent-native` `ACCESS_TOKEN`):

```bash
export ACCESS_TOKEN='your-token-here'

curl -s -X POST \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"operator-verify","version":"1.0"}}}' \
  http://localhost:3000/_agent-native/mcp
```

**Observed (2026-06-17):** JSON result with `serverInfo.name` = `"Plan"`, `protocolVersion` `"2024-11-05"`.
GET on the MCP path returns **405** (method not allowed) — use POST for verification.

---

## 5. Verify plan persistence (volume-backed SQLite)

Plans created via MCP or the UI are stored in SQLite on the Docker volume (D2, D8), not in the image.

### Automated smoke (file survives restart)

```bash
cd wave-orchestrator
docker compose -f docker-compose.agent-native-plans.yml exec agent-native-plans stat /app/data/app.db
docker compose -f docker-compose.agent-native-plans.yml restart agent-native-plans
sleep 3
docker compose -f docker-compose.agent-native-plans.yml exec agent-native-plans stat /app/data/app.db
curl -s -o /dev/null -w "post_restart_health: %{http_code}\n" http://localhost:3000/health
```

**Observed (2026-06-17):** Same inode and `Modify` timestamp on `app.db` after restart; `/health` still **200**.

### Operator smoke (plan row survives restart)

1. Ensure MCP is repointed (§2) and `visual-plan` skill is installed (`npx @agent-native/core@latest skills add visual-plan`).
2. In Cursor or Claude Code, run:

   ```
   /visual-plan plan/tripll-dashboard-ui-wave-plan.md
   ```

   (Or any wave-plan under `plan/`. Large files may need interactive import — see spike runbook.)

3. Note the plan URL, e.g. `http://localhost:3000/plans/plan-<id>`.
4. Restart the container: `make plans-down && make plans-up` (or `docker compose … restart`).
5. Re-open the plan URL in the browser — the plan should still be listed and load.

If the plan disappears, check that compose still mounts `agent-native-plans-data:/app/data` and that you did not run `docker compose down -v` (that deletes the volume).

---

## 6. Manual MCP verification checklist (operator)

| Step | Action | Pass criterion |
|------|--------|----------------|
| 1 | `make plans-up` | Container **Up**, port **3000** published |
| 2 | §3 curl health | `/health` → **200** |
| 3 | §4b MCP initialize | JSON `result.serverInfo.name` = `"Plan"` |
| 4 | Client MCP list | Localhost server visible; hosted plan.agent-native.com entry removed or disabled |
| 5 | `/visual-plan` on a wave-plan | New plan URL under `http://localhost:3000/plans/…` |
| 6 | Container restart | Plan URL still loads (§5) |
| 7 | Agent logs (optional) | No outbound calls to `plan.agent-native.com` during step 5 |

---

## 7. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `make plans-up` exits 1 | Missing `.env.agent-native` | Copy example, fill all `REPLACE_*` secrets |
| MCP 401 | Wrong or missing bearer | Match `ACCESS_TOKEN` in client header to env file |
| MCP "Not Acceptable" on POST | Missing `Accept` header | Include `Accept: application/json, text/event-stream` |
| Plans vanish after restart | Volume removed | Avoid `docker compose down -v`; use named volume from compose file |
| Skill still hits hosted URL | Old MCP entry | Re-run §2 Option A or remove hosted entry manually |

---

## Phase 3 exit criteria

| # | Criterion | Status |
|---|-----------|--------|
| 1 | MCP documented at `http://localhost:3000/_agent-native/mcp` + bearer auth | Done (this runbook) |
| 2 | curl health steps documented and verified | Done (§3) |
| 3 | Volume persistence documented | Done (§5) |
| 4 | Operator MCP verification checklist | Done (§6) |
| 5 | Plans via skill in local UI; no hosted leak | **Pending operator** — run §6 after repointing MCP |

## Next (Phase 4 — not started)

Hybrid tripll links: `PLANS_BASE_URL=http://localhost:3000`, operator runbook start order, optional dashboard header link — see wave plan Phase 4.

## References

- [Agent-Native Deployment — Docker](https://www.agent-native.com/docs/deployment#docker)
- [`docker-compose.agent-native-plans.yml`](../../docker-compose.agent-native-plans.yml)
- [`.env.agent-native.example`](../../.env.agent-native.example)
- [`agent-native-plans-spike.md`](agent-native-plans-spike.md) (Phase 0)
- [`plan/tripll-agent-native-visual-plans-evaluation.md`](../../../plan/tripll-agent-native-visual-plans-evaluation.md)
