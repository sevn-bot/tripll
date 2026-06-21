"""tripll.api — FastAPI control-plane for the wave-orchestrator (W4).

The control plane is a thin HTTP layer over the ledger, runs directory, and
the ``tripll`` CLI.  It **never** runs agents itself — it launches/controls
runs as detached OS-level subprocesses that outlive the server.

Exports:
    create_app — construct and return the FastAPI application.
"""

from __future__ import annotations

from tripll.api.app import create_app

__all__ = ["create_app"]
