"""Operator configuration — four-layer resolution spine (W13).

Exports:
    ProviderConfig — per-backend routing limits.
    RepoConfig — repo-scoped paths from ``tripll.toml``.
    ConfigSources — which layer supplied each setting.
    TripllConfig — resolved operator configuration.
    load_config — merge env → repo → user → defaults.
    merge_model_table — shallow merge for agent model tables.
    resolve_agent_model — SKW-style model precedence chain.
    resolve_openai_compatible — coerce OpenAI-compatible provider settings.
    user_config_path — ``~/.config/tripll/config.toml``.
    repo_config_path — ``<repo_root>/tripll.toml``.
    wave_plan_template_path — packaged v3 template via importlib.resources.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from typing import Any, Literal

from tripll.config.providers import (
    DEEPSEEK_V4_FLASH_MODEL,
    OPENAI_COMPATIBLE_PROVIDERS,
    OpenAiCompatibleProviderConfig,
    coerce_openai_compatible,
)
from tripll.repo_root import resolve_repo_root
from tripll.review import ReviewConfig, review_config_from_raw
from tripll.skw.agent_config import merge_model_table
from tripll.tracing.config import TracingConfig, parse_tracing_config

__all__ = [
    "DEEPSEEK_V4_FLASH_MODEL",
    "OPENAI_COMPATIBLE_PROVIDERS",
    "ConfigSources",
    "ProviderConfig",
    "RepoConfig",
    "ReviewConfig",
    "RulesConfig",
    "TripllConfig",
    "load_config",
    "merge_model_table",
    "repo_config_path",
    "resolve_agent_model",
    "resolve_openai_compatible",
    "user_config_path",
    "wave_plan_template_path",
]

LayerName = Literal["defaults", "user", "repo", "env"]
_PROVIDER_NAMES = ("claude_code", "cursor_local", "cursor_cloud", "nous_research")

_BUILTIN_DEFAULTS: dict[str, Any] = {
    "default_provider": "claude_code",
    "providers": {
        "claude_code": {"max_parallel": 3, "default_model": "claude-sonnet-5"},
        "cursor_local": {"max_parallel": 5, "default_model": "auto"},
        "cursor_cloud": {"max_parallel": 3, "default_model": "auto"},
        "nous_research": {
            "max_parallel": 2,
            "default_model": DEEPSEEK_V4_FLASH_MODEL,
            "base_url": "https://inference-api.nousresearch.com/v1",
            "api_key_env": "NOUS_API_KEY",
            "kind": "openai_compatible",
        },
    },
    "tracing": {
        "enabled": True,
        "sinks": ["sqlite", "jsonl"],
        "retention_days": 30,
        "capture": "shape",
    },
    "repo_root": ".",
    "specs_dir": "docs/specs",
    "prds_dir": "docs/prds",
    "plans_dir": "docs/plans",
    "review": {
        "provider": "mergecraft",
        "ref": "pre-0.0.1",
        "posture": "review_only",
        "ci": {
            "push": "disabled",
            "shell": "disabled",
            "status_checks": True,
            "model": "anthropic/claude-sonnet",
        },
    },
    "rules": {
        "enabled": True,
        "dir": ".tripll/rules",
        "context_dir": ".tripll/context",
        "auto_propose": True,
        "pack_budget_tokens": 1200,
        "executable": "ast-grep",
    },
}


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Per-provider routing limits (no credentials — R24).

    Args:
        max_parallel (int): Concurrent dispatch ceiling for this backend.
        default_model (str): Default model id when a wave does not declare one.
        kind (str): ``cli`` for subprocess backends; ``openai_compatible`` for HTTP APIs.
        base_url (str | None): OpenAI-compatible root URL when ``kind=openai_compatible``.
        api_key_env (str | None): Env var holding the bearer token for HTTP backends.
    """

    max_parallel: int = 3
    default_model: str = "auto"
    kind: str = "cli"
    base_url: str | None = None
    api_key_env: str | None = None


@dataclass(frozen=True, slots=True)
class RulesConfig:
    """Derived rules and context-module settings ([rules] table).

    Args:
        enabled (bool): When False, derive and brief packing are no-ops.
        dir (str): Rendered rule files directory (committed).
        context_dir (str): On-demand context modules directory (committed).
        auto_propose (bool): Findings may propose rules; operator activates (R27).
        pack_budget_tokens (int): Token ceiling for rules+context in one brief.
        executable (str): Executable backend (``off`` | ``ast-grep``); W4 implements.
    """

    enabled: bool = True
    dir: str = ".tripll/rules"
    context_dir: str = ".tripll/context"
    auto_propose: bool = True
    pack_budget_tokens: int = 1200
    executable: str = "ast-grep"


@dataclass(frozen=True, slots=True)
class RepoConfig:
    """Repo-scoped layout from ``tripll.toml``.

    Args:
        repo_root (str): Repo root relative path marker.
        specs_dir (str): Spec documents directory.
        prds_dir (str): PRD documents directory.
        plans_dir (str): Wave-plan documents directory.
    """

    repo_root: str = "."
    specs_dir: str = "docs/specs"
    prds_dir: str = "docs/prds"
    plans_dir: str = "docs/plans"


@dataclass(frozen=True, slots=True)
class ConfigSources:
    """Record which layer won for key settings.

    Args:
        default_provider (LayerName): Source of ``default_provider``.
        user_config (Path | None): User config file when present.
        repo_config (Path | None): Repo config file when present.
    """

    default_provider: LayerName = "defaults"
    user_config: Path | None = None
    repo_config: Path | None = None


@dataclass(frozen=True, slots=True)
class TripllConfig:
    """Resolved operator configuration after four-layer merge.

    Args:
        default_provider (str): Active backend name.
        providers (dict[str, ProviderConfig]): Per-backend settings.
        tracing (TracingConfig): Tracing block (plan + env applied).
        repo (RepoConfig): Repo layout settings.
        rules (RulesConfig): Derived rules and context-module settings.
        review (ReviewConfig): mergeCraft review posture and CI inputs.
        sources (ConfigSources): Provenance for diagnostics.
        raw (dict[str, Any]): Merged TOML tables before dataclass coercion.
    """

    default_provider: str
    providers: dict[str, ProviderConfig]
    tracing: TracingConfig
    repo: RepoConfig
    rules: RulesConfig
    review: ReviewConfig
    sources: ConfigSources
    raw: dict[str, Any] = field(default_factory=dict)


def user_config_path() -> Path:
    """Return the user-level config file path.

    Returns:
        Path: ``~/.config/tripll/config.toml``.

    Examples:
        >>> user_config_path().name
        'config.toml'
    """
    return Path.home() / ".config" / "tripll" / "config.toml"


def repo_config_path(repo_root: Path | None = None) -> Path:
    """Return the repo-level config file path.

    Args:
        repo_root (Path | None): Repo root; resolved from CWD when omitted.

    Returns:
        Path: ``<repo_root>/tripll.toml``.

    Examples:
        >>> repo_config_path(Path("/tmp/r")).name
        'tripll.toml'
    """
    root = repo_root if repo_root is not None else resolve_repo_root()
    return root / "tripll.toml"


def wave_plan_template_path() -> Path:
    """Return the packaged v3 wave-plan template (importlib.resources).

    Returns:
        Path: Readable path to ``templates/wave-plan-template.md``.

    Raises:
        FileNotFoundError: When the template is absent from the wheel.

    Examples:
        >>> wave_plan_template_path().name
        'wave-plan-template.md'
    """
    resource = files("tripll.templates").joinpath("wave-plan-template.md")
    with resource.open("rb") as handle:
        _ = handle.read(1)
    return Path(str(resource))


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _provider_row(raw: dict[str, Any], name: str) -> dict[str, Any]:
    providers_raw = raw.get("providers")
    if not isinstance(providers_raw, dict):
        return {}
    row = providers_raw.get(name)
    return dict(row) if isinstance(row, dict) else {}


def _coerce_providers(raw: dict[str, Any]) -> dict[str, ProviderConfig]:
    out: dict[str, ProviderConfig] = {}
    for name in _PROVIDER_NAMES:
        row = _provider_row(raw, name)
        defaults = _BUILTIN_DEFAULTS["providers"][name]
        mp = row.get("max_parallel", defaults["max_parallel"])
        dm = row.get("default_model", defaults["default_model"])
        kind = str(row.get("kind") or defaults.get("kind") or "cli")
        base_url = row.get("base_url", defaults.get("base_url"))
        api_key_env = row.get("api_key_env", defaults.get("api_key_env"))
        out[name] = ProviderConfig(
            max_parallel=int(mp) if mp is not None else int(defaults["max_parallel"]),
            default_model=str(dm) if dm is not None else str(defaults["default_model"]),
            kind=kind,
            base_url=str(base_url) if base_url is not None else None,
            api_key_env=str(api_key_env) if api_key_env is not None else None,
        )
    return out


def resolve_openai_compatible(cfg: TripllConfig, name: str) -> OpenAiCompatibleProviderConfig:
    """Return validated OpenAI-compatible settings for *name*.

    Args:
        cfg (TripllConfig): Loaded operator config.
        name (str): Provider id (must be in :data:`OPENAI_COMPATIBLE_PROVIDERS`).

    Returns:
        OpenAiCompatibleProviderConfig: Endpoint + model defaults.

    Raises:
        KeyError: When *name* is not an OpenAI-compatible provider.

    Examples:
        >>> c = load_config()
        >>> resolve_openai_compatible(c, "nous_research").default_model
        'deepseek/deepseek-v4-flash'
    """
    if name not in OPENAI_COMPATIBLE_PROVIDERS:
        msg = f"{name!r} is not an OpenAI-compatible provider"
        raise KeyError(msg)
    row = _provider_row(cfg.raw, name)
    provider_cfg = cfg.providers.get(name)
    if provider_cfg is not None:
        if provider_cfg.base_url:
            row.setdefault("base_url", provider_cfg.base_url)
        if provider_cfg.api_key_env:
            row.setdefault("api_key_env", provider_cfg.api_key_env)
        row.setdefault("default_model", provider_cfg.default_model)
        row.setdefault("max_parallel", provider_cfg.max_parallel)
    return coerce_openai_compatible(name, row)


def _coerce_repo(raw: dict[str, Any]) -> RepoConfig:
    return RepoConfig(
        repo_root=str(raw.get("repo_root") or _BUILTIN_DEFAULTS["repo_root"]),
        specs_dir=str(raw.get("specs_dir") or _BUILTIN_DEFAULTS["specs_dir"]),
        prds_dir=str(raw.get("prds_dir") or _BUILTIN_DEFAULTS["prds_dir"]),
        plans_dir=str(raw.get("plans_dir") or _BUILTIN_DEFAULTS["plans_dir"]),
    )


def _coerce_rules(raw: dict[str, Any]) -> RulesConfig:
    defaults = _BUILTIN_DEFAULTS["rules"]
    rules_raw = raw.get("rules")
    row: dict[str, Any] = rules_raw if isinstance(rules_raw, dict) else {}
    enabled = row.get("enabled", defaults["enabled"])
    auto_propose = row.get("auto_propose", defaults["auto_propose"])
    pack_budget = row.get("pack_budget_tokens", defaults["pack_budget_tokens"])
    return RulesConfig(
        enabled=bool(enabled),
        dir=str(row.get("dir") or defaults["dir"]),
        context_dir=str(row.get("context_dir") or defaults["context_dir"]),
        auto_propose=bool(auto_propose),
        pack_budget_tokens=int(pack_budget),
        executable=str(row.get("executable") or defaults["executable"]),
    )


def _apply_env_overrides(raw: dict[str, Any]) -> tuple[dict[str, Any], LayerName | None]:
    """Apply ``TRIPLL_*`` env overrides (highest precedence).

    Returns:
        tuple[dict[str, Any], LayerName | None]: Merged dict and provider layer flag.
    """
    merged = dict(raw)
    touched = False

    provider_env = os.environ.get("TRIPLL_DEFAULT_PROVIDER", "").strip()
    if provider_env:
        merged["default_provider"] = provider_env
        touched = True

    model_env = os.environ.get("TRIPLL_DEFAULT_MODEL", "").strip()
    max_par_env = os.environ.get("TRIPLL_MAX_PARALLEL", "").strip()
    if model_env or max_par_env:
        providers = dict(merged.get("providers") or {})
        default_name = str(merged.get("default_provider") or "claude_code")
        row = dict(providers.get(default_name) or {})
        if model_env:
            row["default_model"] = model_env
            touched = True
        if max_par_env:
            try:
                row["max_parallel"] = int(max_par_env)
                touched = True
            except ValueError:
                pass
        providers[default_name] = row
        merged["providers"] = providers

    return merged, "env" if touched else None


def load_config(*, repo_root: Path | None = None) -> TripllConfig:
    """Load configuration from four layers (env highest).

    Resolution order: **env (``TRIPLL_*``) → ``./tripll.toml`` →
    ``~/.config/tripll/config.toml`` → built-in defaults**.

    Args:
        repo_root (Path | None): Repo root for ``tripll.toml`` lookup.

    Returns:
        TripllConfig: Fully merged configuration.

    Examples:
        >>> cfg = load_config()
        >>> cfg.default_provider in _PROVIDER_NAMES
        True
    """
    root = repo_root if repo_root is not None else resolve_repo_root()
    user_path = user_config_path()
    repo_path = repo_config_path(root)

    merged: dict[str, Any] = dict(_BUILTIN_DEFAULTS)
    sources = ConfigSources(user_config=user_path if user_path.is_file() else None)

    user_data = _read_toml(user_path)
    if user_data:
        merged = _deep_merge(merged, user_data)

    repo_data = _read_toml(repo_path)
    if repo_data:
        merged = _deep_merge(merged, repo_data)
        sources = ConfigSources(
            default_provider="repo"
            if "default_provider" in repo_data
            else sources.default_provider,
            user_config=sources.user_config,
            repo_config=repo_path,
        )

    merged, env_layer = _apply_env_overrides(merged)
    if env_layer == "env":
        sources = ConfigSources(
            default_provider="env",
            user_config=sources.user_config,
            repo_config=sources.repo_config,
        )
    elif "default_provider" in repo_data:
        sources = ConfigSources(
            default_provider="repo",
            user_config=sources.user_config,
            repo_config=repo_path if repo_data else None,
        )
    elif "default_provider" in user_data:
        sources = ConfigSources(
            default_provider="user",
            user_config=user_path,
            repo_config=sources.repo_config,
        )

    tracing = parse_tracing_config({"tracing": merged.get("tracing")})
    review_raw = merged.get("review")
    return TripllConfig(
        default_provider=str(merged.get("default_provider") or "claude_code"),
        providers=_coerce_providers(merged),
        tracing=tracing,
        repo=_coerce_repo(merged),
        rules=_coerce_rules(merged),
        review=review_config_from_raw(review_raw if isinstance(review_raw, dict) else None),
        sources=sources,
        raw=merged,
    )


def resolve_agent_model(
    cfg: TripllConfig,
    *,
    agent_id: str,
    wave_data: dict[str, Any] | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    """Resolve model parameters using SKW merge-table precedence (W13.2).

    Order: ``[agent]`` → ``[agent.models.<id>]`` → wave global → wave per-agent
    → wave per-stage → env (``TRIPLL_DEFAULT_MODEL``).

    Args:
        cfg (TripllConfig): Loaded operator config (``raw`` may hold ``agent`` tables).
        agent_id (str): Target agent id (e.g. ``wave-runner``).
        wave_data (dict[str, Any] | None): Parsed v3 plan dict.
        stage (str | None): Pipeline stage name for per-stage overrides.

    Returns:
        dict[str, Any]: Merged model parameter table.

    Examples:
        >>> c = load_config()
        >>> resolve_agent_model(c, agent_id="wave-runner")["model"]
        'claude-sonnet-5'
    """
    raw = cfg.raw
    agent_raw = raw.get("agent")
    agent_cfg: dict[str, Any] = agent_raw if isinstance(agent_raw, dict) else {}
    agent_global = {k: v for k, v in agent_cfg.items() if k != "models" and not isinstance(v, dict)}
    models_raw = agent_cfg.get("models")
    models_table: dict[str, Any] = models_raw if isinstance(models_raw, dict) else {}
    agent_raw_row = models_table.get(agent_id)
    by_agent: dict[str, Any] = agent_raw_row if isinstance(agent_raw_row, dict) else {}

    merged = merge_model_table({}, agent_global)
    merged = merge_model_table(merged, by_agent)

    default_provider = cfg.default_provider
    provider_row = cfg.providers.get(default_provider)
    if provider_row and "model" not in merged:
        merged["model"] = provider_row.default_model

    if wave_data is not None:
        pipeline_raw = wave_data.get("pipeline")
        pipeline: dict[str, Any] = pipeline_raw if isinstance(pipeline_raw, dict) else {}
        wave_global_raw = pipeline.get("model")
        wave_global: dict[str, Any] = wave_global_raw if isinstance(wave_global_raw, dict) else {}
        wave_models_raw = pipeline.get("models")
        wave_models: dict[str, Any] = wave_models_raw if isinstance(wave_models_raw, dict) else {}
        wave_agent_raw = wave_models.get(agent_id)
        wave_by_agent: dict[str, Any] = wave_agent_raw if isinstance(wave_agent_raw, dict) else {}
        merged = merge_model_table(merged, wave_global)
        merged = merge_model_table(merged, wave_by_agent)
        if stage:
            stage_table = pipeline.get(stage)
            if isinstance(stage_table, dict):
                stage_model = stage_table.get("model")
                if isinstance(stage_model, dict):
                    merged = merge_model_table(merged, stage_model)

    env_model = os.environ.get("TRIPLL_DEFAULT_MODEL", "").strip()
    if env_model:
        merged["model"] = env_model

    if "model" not in merged and provider_row:
        merged["model"] = provider_row.default_model

    return merged
