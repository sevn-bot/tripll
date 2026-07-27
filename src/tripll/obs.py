"""tripll.obs — optional Logfire/OpenTelemetry observability (TRACE-03).

Single configurator for Logfire, local trace sinks, scrubbing, and httpx/pydantic-ai
instrumentation. Safe no-op when the ``obs`` extra is absent.

Exports:
    configure_observability — configure tracing when available; otherwise no-op.
    get_tracing_config — resolved tracing config after configure (or defaults).
    SERVICE_NAME — default service name.
"""

from __future__ import annotations

import os
import re
from typing import Any

from loguru import logger

from tripll.log_redact import load_hide_keys
from tripll.tracing.config import TracingConfig, parse_tracing_config

SERVICE_NAME = "tripll"

_configured = False
_tracing_config: TracingConfig = TracingConfig()


def get_tracing_config() -> TracingConfig:
    """Return the resolved tracing config (call :func:`configure_observability` first).

    Returns:
        TracingConfig: Effective tracing settings for this process.
    """
    return _tracing_config


def _scrubbing_options() -> Any | None:
    try:
        import logfire
    except ImportError:
        return None
    hide_keys = load_hide_keys()
    patterns = [re.compile(rf"(?i){re.escape(key)}") for key in hide_keys]

    def _callback(match: Any) -> Any | None:
        path = match.path if hasattr(match, "path") else ()
        joined = ".".join(str(part) for part in path)
        if any(p.search(joined) for p in patterns):
            return "[redacted]"
        return None

    return logfire.ScrubbingOptions(callback=_callback, extra_patterns=tuple(patterns))


def _advanced_options(config: TracingConfig) -> Any | None:
    try:
        from logfire import AdvancedOptions
    except ImportError:
        return None
    for exp in config.exporters:
        if exp.type == "logfire" and exp.base_url:
            return AdvancedOptions(base_url=exp.base_url)
    base_url = os.environ.get("LOGFIRE_BASE_URL", "").strip()
    if base_url:
        return AdvancedOptions(base_url=base_url)
    return None


def _otlp_processors(config: TracingConfig) -> list[Any]:
    processors: list[Any] = []
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return processors
    for exp in config.exporters:
        if exp.type != "otlp":
            continue
        endpoint = exp.endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not endpoint:
            continue
        exporter = OTLPSpanExporter(endpoint=endpoint)
        processors.append(BatchSpanProcessor(exporter))
    return processors


def configure_observability(
    *,
    service_name: str = SERVICE_NAME,
    plan: dict[str, Any] | None = None,
) -> bool:
    """Configure Logfire tracing and store the resolved tracing config.

    Local sinks are created per run via :func:`tripll.tracing.init_run_tracing`.
    This function is the sole SDK setup entry point in ``src/`` (TRACE-03).

    Args:
        service_name (str): Service name reported to exporters.
        plan (dict[str, Any] | None): Optional parsed v3 plan for ``[tracing]``.

    Returns:
        bool: ``True`` when tracing is enabled and/or Logfire was configured.

    Examples:
        >>> import os
        >>> os.environ["TRIPLL_TRACE"] = "0"
        >>> configure_observability()
        False
    """
    global _configured, _tracing_config
    merged = parse_tracing_config(plan)
    if service_name:
        merged = TracingConfig(
            enabled=merged.enabled,
            service_name=service_name,
            sinks=merged.sinks,
            retention_days=merged.retention_days,
            capture=merged.capture,
            exporters=merged.exporters,
        )

    if _configured:
        _tracing_config = merged
        return _tracing_config.enabled

    _tracing_config = merged
    _configured = True

    if not _tracing_config.enabled:
        return False

    try:
        import logfire
    except ImportError:
        return _tracing_config.has_local_sinks

    token = os.environ.get("LOGFIRE_TOKEN", "").strip()
    wants_logfire = _tracing_config.wants_logfire or bool(token)
    advanced = _advanced_options(_tracing_config)
    processors = _otlp_processors(_tracing_config)
    scrubbing = _scrubbing_options()

    if not wants_logfire and not processors:
        return _tracing_config.has_local_sinks

    try:
        kwargs: dict[str, Any] = {
            "service_name": _tracing_config.service_name,
            "send_to_logfire": "if-token-present",
            "inspect_arguments": False,
        }
        if token:
            kwargs["token"] = token
        if advanced is not None:
            kwargs["advanced"] = advanced
        if scrubbing is not None:
            kwargs["scrubbing"] = scrubbing
        if processors:
            kwargs["additional_span_processors"] = processors
        logfire.configure(**kwargs)
        logfire.instrument_httpx(capture_all=False)
        logfire.instrument_pydantic_ai()
    except Exception as exc:
        logger.warning(f"logfire configuration skipped: {exc}")
        return _tracing_config.has_local_sinks

    logger.debug(
        "observability enabled (service={}, local_sinks={}, logfire={})",
        _tracing_config.service_name,
        _tracing_config.sinks,
        wants_logfire,
    )
    return True
