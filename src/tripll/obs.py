"""tripll.obs — optional Logfire/OpenTelemetry observability.

Module: tripll.obs
Depends: logfire (optional, via the ``obs`` extra)

Observability is opt-in and best-effort: when the ``obs`` extra is not installed
or no ``LOGFIRE_TOKEN`` is present, ``configure_observability`` is a no-op and never
emits network calls. This mirrors sevn's ``send_to_logfire="if-token-present"`` idiom.

Exports:
    configure_observability — configure Logfire tracing when available; otherwise no-op.
"""

from __future__ import annotations

import os

from loguru import logger

#: Service name reported to Logfire / OTel backends.
SERVICE_NAME = "tripll"


def configure_observability(*, service_name: str = SERVICE_NAME) -> bool:
    """Configure Logfire tracing when the ``obs`` extra and a token are available.

    Safe to call unconditionally at startup. Does nothing (and never raises) when
    ``logfire`` is not installed. When installed, Logfire only ships data if a token
    is resolvable (``LOGFIRE_TOKEN``), thanks to ``send_to_logfire="if-token-present"``.

    Args:
        service_name (str): Service name reported to the tracing backend.
            Defaults to ``"tripll"``.

    Returns:
        bool: True when Logfire was configured, False when skipped (no extra/token).

    Examples:
        >>> import os
        >>> os.environ.pop("LOGFIRE_TOKEN", None)
        >>> configure_observability()
        False
    """
    try:
        import logfire
    except ImportError:
        return False

    if not os.environ.get("LOGFIRE_TOKEN"):
        return False

    try:
        logfire.configure(service_name=service_name, send_to_logfire="if-token-present")
        logfire.instrument_httpx(capture_all=True)
    except Exception as exc:  # observability must never break the CLI
        logger.warning(f"logfire configuration skipped: {exc}")
        return False

    logger.debug(f"logfire observability enabled (service={service_name})")
    return True
