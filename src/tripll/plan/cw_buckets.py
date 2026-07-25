"""Coordination-wave hotspot reference buckets (W4.4 corpus replay)."""

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


def default_cw_hotspots() -> dict[str, list[str]]:
    """Return coordination-wave hotspots from the legacy reference buckets."""
    return {key: list(paths) for key, paths in LEGACY_CW_BUCKETS.items()}
