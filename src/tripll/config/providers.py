"""OpenAI-compatible provider registry and validation (W2 / #76).

Exports:
    OPENAI_COMPATIBLE_PROVIDERS — built-in OpenAI-compatible backend ids.
    NOUS_RESEARCH_* — Nous Research defaults for DeepSeek V4 Flash.
    OpenAiCompatibleProviderConfig — routing + endpoint settings (no credentials).
    KNOWN_NOUS_MODELS — selectable model ids on the Nous inference gateway.
    coerce_openai_compatible — parse one ``[providers.*]`` row.
    validate_base_url — reject unsafe ``base_url`` values (L2).
    resolve_api_key — read API key from env (R24: never from config files).
    build_chat_completions_url — join base URL + ``/chat/completions``.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DEEPSEEK_V4_FLASH_MODEL",
    "KNOWN_NOUS_MODELS",
    "NOUS_RESEARCH_API_KEY_ENV",
    "NOUS_RESEARCH_DEFAULT_BASE_URL",
    "OPENAI_COMPATIBLE_PROVIDERS",
    "OpenAiCompatibleProviderConfig",
    "build_chat_completions_url",
    "coerce_openai_compatible",
    "openai_compatible_chat_completion",
    "resolve_api_key",
    "validate_base_url",
]

OPENAI_COMPATIBLE_PROVIDERS: frozenset[str] = frozenset({"nous_research"})

NOUS_RESEARCH_DEFAULT_BASE_URL = "https://inference-api.nousresearch.com/v1"
NOUS_RESEARCH_API_KEY_ENV = "NOUS_API_KEY"
DEEPSEEK_V4_FLASH_MODEL = "deepseek/deepseek-v4-flash"

KNOWN_NOUS_MODELS: frozenset[str] = frozenset(
    {
        DEEPSEEK_V4_FLASH_MODEL,
        "deepseek/deepseek-v4-pro",
    }
)

_BASE_URL_FORBIDDEN = re.compile(r"[;\s]|(?:\.\.)")


@dataclass(frozen=True, slots=True)
class OpenAiCompatibleProviderConfig:
    """OpenAI-compatible provider routing (credentials live in env only — R24).

    Args:
        name (str): Provider id (e.g. ``nous_research``).
        max_parallel (int): Concurrent dispatch ceiling.
        default_model (str): Default model when a wave omits ``model``.
        base_url (str): OpenAI-compatible API root (includes ``/v1`` when required).
        api_key_env (str): Environment variable holding the bearer token.
    """

    name: str
    max_parallel: int = 2
    default_model: str = DEEPSEEK_V4_FLASH_MODEL
    base_url: str = NOUS_RESEARCH_DEFAULT_BASE_URL
    api_key_env: str = NOUS_RESEARCH_API_KEY_ENV


def validate_base_url(value: str) -> str:
    """Reject unsafe ``base_url`` values (L2 allowlist).

    Args:
        value (str): Candidate base URL from config.

    Returns:
        str: Stripped URL.

    Raises:
        ValueError: When the URL contains forbidden characters.

    Examples:
        >>> validate_base_url("https://inference-api.nousresearch.com/v1")
        'https://inference-api.nousresearch.com/v1'
    """
    url = value.strip()
    if not url:
        msg = "base_url must not be empty"
        raise ValueError(msg)
    if _BASE_URL_FORBIDDEN.search(url):
        msg = f"base_url contains forbidden characters: {value!r}"
        raise ValueError(msg)
    if not url.startswith(("http://", "https://")):
        msg = f"base_url must be http(s): {value!r}"
        raise ValueError(msg)
    return url


def validate_api_key_env(value: str) -> str:
    """Reject unsafe ``api_key_env`` names (L2 allowlist).

    Args:
        value (str): Environment variable name from config.

    Returns:
        str: Normalised env var name.

    Raises:
        ValueError: When the name is empty or contains forbidden characters.

    Examples:
        >>> validate_api_key_env("NOUS_API_KEY")
        'NOUS_API_KEY'
    """
    name = value.strip()
    if not name or _BASE_URL_FORBIDDEN.search(name):
        msg = f"api_key_env is invalid: {value!r}"
        raise ValueError(msg)
    return name


def build_chat_completions_url(base_url: str) -> str:
    """Return the chat-completions endpoint for an OpenAI-compatible base URL.

    Args:
        base_url (str): Provider root (typically ends with ``/v1``).

    Returns:
        str: Full ``…/chat/completions`` URL.

    Examples:
        >>> build_chat_completions_url("https://inference-api.nousresearch.com/v1")
        'https://inference-api.nousresearch.com/v1/chat/completions'
    """
    root = base_url.rstrip("/")
    if root.endswith("/chat/completions"):
        return root
    return f"{root}/chat/completions"


def coerce_openai_compatible(
    name: str, row: dict[str, Any] | None
) -> OpenAiCompatibleProviderConfig:
    """Parse one ``[providers.<name>]`` table for an OpenAI-compatible backend.

    Args:
        name (str): Provider id.
        row (dict[str, Any] | None): Raw TOML table or None for defaults.

    Returns:
        OpenAiCompatibleProviderConfig: Coerced settings.

    Examples:
        >>> cfg = coerce_openai_compatible("nous_research", None)
        >>> cfg.default_model
        'deepseek/deepseek-v4-flash'
    """
    defaults = OpenAiCompatibleProviderConfig(name=name)
    if not isinstance(row, dict):
        return defaults
    max_par = row.get("max_parallel", defaults.max_parallel)
    model_raw = row.get("default_model", defaults.default_model)
    base_raw = row.get("base_url", defaults.base_url)
    key_env_raw = row.get("api_key_env", defaults.api_key_env)
    return OpenAiCompatibleProviderConfig(
        name=name,
        max_parallel=int(max_par) if max_par is not None else defaults.max_parallel,
        default_model=str(model_raw).strip() if model_raw is not None else defaults.default_model,
        base_url=validate_base_url(str(base_raw)),
        api_key_env=validate_api_key_env(str(key_env_raw)),
    )


def resolve_api_key(cfg: OpenAiCompatibleProviderConfig) -> str | None:
    """Read the bearer token from the configured env var (R24).

    Args:
        cfg (OpenAiCompatibleProviderConfig): Provider settings.

    Returns:
        str | None: API key when present and non-empty.

    Examples:
        >>> import os
        >>> c = OpenAiCompatibleProviderConfig(name="nous_research")
        >>> os.environ.pop("NOUS_API_KEY", None)
        >>> resolve_api_key(c) is None
        True
    """
    raw = os.environ.get(cfg.api_key_env, "").strip()
    return raw or None


def openai_compatible_chat_completion(
    cfg: OpenAiCompatibleProviderConfig,
    *,
    model: str,
    messages: list[dict[str, str]],
    timeout_s: float = 60.0,
) -> dict[str, Any]:
    """POST one non-streaming chat completion (stdlib HTTP — no SDK dependency).

    Args:
        cfg (OpenAiCompatibleProviderConfig): Provider endpoint settings.
        model (str): Model id (e.g. ``deepseek/deepseek-v4-flash``).
        messages (list[dict[str, str]]): OpenAI-style message list.
        timeout_s (float): HTTP read timeout in seconds.

    Returns:
        dict[str, Any]: Parsed JSON response body.

    Raises:
        RuntimeError: When the API key is missing or the HTTP call fails.

    Examples:
        >>> import os
        >>> c = OpenAiCompatibleProviderConfig(name="nous_research")
        >>> os.environ.pop("NOUS_API_KEY", None)
        >>> try:
        ...     openai_compatible_chat_completion(c, model="deepseek/deepseek-v4-flash", messages=[])
        ... except RuntimeError as exc:
        ...     "missing" in str(exc).lower()
        ... else:
        ...     False
        True
    """
    api_key = resolve_api_key(cfg)
    if not api_key:
        msg = f"{cfg.api_key_env} is not set — export it before calling Nous Research"
        raise RuntimeError(msg)

    url = build_chat_completions_url(cfg.base_url)
    payload = json.dumps({"model": model, "messages": messages, "stream": False}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        msg = f"Nous API HTTP {exc.code}: {detail}"
        raise RuntimeError(msg) from exc
    except urllib.error.URLError as exc:
        msg = f"Nous API request failed: {exc.reason}"
        raise RuntimeError(msg) from exc

    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        msg = "Nous API returned non-object JSON"
        raise TypeError(msg)
    return parsed
