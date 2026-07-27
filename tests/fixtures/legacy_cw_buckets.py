"""Opt-in sevn coordination-wave reference buckets for corpus replay (R9, W8)."""

from __future__ import annotations

LEGACY_CW_BUCKETS: dict[str, list[str]] = {
    "CW-1": ["src/sevn/gateway/agent_turn.py"],
    "CW-2": ["src/sevn/gateway/http_server.py"],
    "CW-3": ["Makefile (ci: line)"],
    "CW-4": [
        "src/sevn/ui/dashboard/app.js",
        "src/sevn/ui/dashboard/api/tab_registry.py",
    ],
    "CW-5": ["infra/sevn.schema.json"],
}
