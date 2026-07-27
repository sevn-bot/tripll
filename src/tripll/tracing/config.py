"""Parse ``[tracing]`` plan config and env overrides (P3.11).

Exports:
    TraceExporter — one configured exporter row.
    TracingConfig — resolved tracing settings.
    parse_tracing_config — parse plan dict + environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Literal

from tripll.tracing.capture import DEFAULT_CAPTURE, CaptureMode, parse_capture_mode

ExporterType = Literal["logfire", "otlp"]
VALID_EXPORTER_TYPES = frozenset({"logfire", "otlp"})


@dataclass(frozen=True, slots=True)
class TraceExporter:
    """One ``[[tracing.exporters]]`` row.

    Args:
        type (ExporterType): ``logfire`` or ``otlp``.
        base_url (str | None): Self-hosted Logfire base URL.
        endpoint (str | None): OTLP HTTP endpoint.
    """

    type: ExporterType
    base_url: str | None = None
    endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class TracingConfig:
    """Resolved tracing configuration for a process or run.

    Args:
        enabled (bool): Master tracing switch after env overrides.
        service_name (str): Service name reported to exporters.
        sinks (tuple[str, ...]): Local sink ids (``sqlite``, ``jsonl``).
        retention_days (int): SQLite retention window.
        capture (CaptureMode): Prompt/completion capture policy.
        exporters (tuple[TraceExporter, ...]): Optional remote exporters.
    """

    enabled: bool = True
    service_name: str = "tripll"
    sinks: tuple[str, ...] = ("sqlite", "jsonl")
    retention_days: int = 30
    capture: CaptureMode = DEFAULT_CAPTURE
    exporters: tuple[TraceExporter, ...] = field(default_factory=tuple)

    @property
    def has_local_sinks(self) -> bool:
        """Return whether any local sink is configured."""
        return bool(self.sinks)

    @property
    def wants_logfire(self) -> bool:
        """Return whether a Logfire exporter is configured."""
        return any(exp.type == "logfire" for exp in self.exporters)


def _parse_exporters(raw: Any) -> tuple[TraceExporter, ...]:
    if not isinstance(raw, list):
        return ()
    out: list[TraceExporter] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        exp_type = str(row.get("type", "")).strip().lower()
        if exp_type not in VALID_EXPORTER_TYPES:
            raise ValueError(f"unknown tracing exporter type={exp_type!r}")
        base_url = row.get("base_url")
        endpoint = row.get("endpoint")
        out.append(
            TraceExporter(
                type=exp_type,  # type: ignore[arg-type]
                base_url=str(base_url).strip() if base_url else None,
                endpoint=str(endpoint).strip() if endpoint else None,
            )
        )
    return tuple(out)


def _parse_tracing_table(raw: dict[str, Any]) -> TracingConfig:
    enabled = bool(raw.get("enabled", True))
    service_name = str(raw.get("service_name") or "tripll")
    sinks_raw = raw.get("sinks", ["sqlite", "jsonl"])
    sinks = tuple(str(s) for s in sinks_raw) if isinstance(sinks_raw, list) else ("sqlite", "jsonl")
    retention = int(raw.get("retention_days", 30))
    capture = parse_capture_mode(raw.get("capture"))
    exporters = _parse_exporters(raw.get("exporters"))
    return TracingConfig(
        enabled=enabled,
        service_name=service_name,
        sinks=sinks,
        retention_days=max(1, retention),
        capture=capture,
        exporters=exporters,
    )


def _env_exporter_overrides() -> list[TraceExporter]:
    exporters: list[TraceExporter] = []
    token = os.environ.get("LOGFIRE_TOKEN", "").strip()
    base_url = os.environ.get("LOGFIRE_BASE_URL", "").strip()
    if token or base_url:
        exporters.append(TraceExporter(type="logfire", base_url=base_url or None))
    otlp = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if otlp:
        exporters.append(TraceExporter(type="otlp", endpoint=otlp))
    return exporters


def parse_tracing_config(plan: dict[str, Any] | None = None) -> TracingConfig:
    """Parse ``[tracing]`` from a v3 plan and apply env precedence.

    Env order: ``TRIPLL_TRACE`` → ``LOGFIRE_TOKEN`` / ``LOGFIRE_BASE_URL`` →
    ``OTEL_EXPORTER_OTLP_ENDPOINT``.

    Args:
        plan (dict[str, Any] | None): Parsed v3 plan dict.

    Returns:
        TracingConfig: Effective tracing settings.
    """
    tracing_raw = (plan or {}).get("tracing") if isinstance(plan, dict) else None
    cfg = _parse_tracing_table(tracing_raw) if isinstance(tracing_raw, dict) else TracingConfig()

    trace_env = os.environ.get("TRIPLL_TRACE")
    if trace_env is not None:
        enabled = trace_env.strip().lower() not in {"0", "false", "no", "off"}
        cfg = TracingConfig(
            enabled=enabled,
            service_name=cfg.service_name,
            sinks=cfg.sinks,
            retention_days=cfg.retention_days,
            capture=cfg.capture,
            exporters=cfg.exporters,
        )

    env_exporters = _env_exporter_overrides()
    if env_exporters:
        merged = list(cfg.exporters)
        for exp in env_exporters:
            if not any(
                existing.type == exp.type and existing.base_url == exp.base_url
                for existing in merged
            ):
                merged.append(exp)
        cfg = TracingConfig(
            enabled=cfg.enabled,
            service_name=cfg.service_name,
            sinks=cfg.sinks,
            retention_days=cfg.retention_days,
            capture=cfg.capture,
            exporters=tuple(merged),
        )
    return cfg
