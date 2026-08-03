"""Tests for Nous Research OpenAI-compatible provider (#76)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from tripll.adapters import BACKENDS, get_adapter
from tripll.adapters.nous_research import NousResearchAdapter
from tripll.config import (
    DEEPSEEK_V4_FLASH_MODEL,
    load_config,
    resolve_agent_model,
    resolve_openai_compatible,
)
from tripll.config.providers import (
    build_chat_completions_url,
    coerce_openai_compatible,
    openai_compatible_chat_completion,
    validate_api_key_env,
    validate_base_url,
)


def test_registry_includes_nous_research() -> None:
    assert "nous_research" in BACKENDS


def test_default_nous_model_is_deepseek_v4_flash() -> None:
    cfg = load_config()
    row = cfg.providers["nous_research"]
    assert row.default_model == DEEPSEEK_V4_FLASH_MODEL
    assert row.kind == "openai_compatible"
    assert row.base_url == "https://inference-api.nousresearch.com/v1"
    assert row.api_key_env == "NOUS_API_KEY"


def test_resolve_openai_compatible_from_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("TRIPLL_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("TRIPLL_DEFAULT_PROVIDER", raising=False)
    cfg_dir = home / ".config" / "tripll"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.toml").write_text(
        "\n".join(
            [
                'default_provider = "nous_research"',
                "",
                "[providers.nous_research]",
                f'default_model = "{DEEPSEEK_V4_FLASH_MODEL}"',
                'base_url = "https://inference-api.nousresearch.com/v1"',
                "max_parallel = 3",
            ]
        ),
        encoding="utf-8",
    )
    cfg = load_config()
    endpoint = resolve_openai_compatible(cfg, "nous_research")
    assert endpoint.default_model == DEEPSEEK_V4_FLASH_MODEL
    assert endpoint.max_parallel == 3
    merged = resolve_agent_model(cfg, agent_id="wave-runner")
    assert merged["model"] == DEEPSEEK_V4_FLASH_MODEL


@pytest.mark.parametrize(
    ("value", "matches"),
    [
        ("https://inference-api.nousresearch.com/v1", False),
        ("https://evil.com;drop", True),
        ("https://evil.com/../secret", True),
        ("ftp://bad", True),
        ("", True),
    ],
)
def test_validate_base_url_rejects_unsafe(value: str, matches: bool) -> None:
    if matches:
        with pytest.raises(ValueError, match=r"."):
            validate_base_url(value)
    else:
        assert validate_base_url(value).startswith("https://")


def test_validate_api_key_env_rejects_unsafe() -> None:
    with pytest.raises(ValueError, match="invalid"):
        validate_api_key_env("NOUS KEY")


def test_build_chat_completions_url() -> None:
    url = build_chat_completions_url("https://inference-api.nousresearch.com/v1")
    assert url.endswith("/chat/completions")


def test_nous_capabilities_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    caps = NousResearchAdapter().capabilities()
    assert caps.available is False
    assert "NOUS_API_KEY" in caps.detail


def test_nous_capabilities_with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "test-key")
    caps = NousResearchAdapter().capabilities()
    assert caps.available is True
    assert DEEPSEEK_V4_FLASH_MODEL in caps.detail


def test_openai_compatible_chat_completion_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOUS_API_KEY", raising=False)
    cfg = coerce_openai_compatible("nous_research", None)
    with pytest.raises(RuntimeError, match="NOUS_API_KEY"):
        openai_compatible_chat_completion(
            cfg,
            model=DEEPSEEK_V4_FLASH_MODEL,
            messages=[{"role": "user", "content": "ping"}],
        )


def test_openai_compatible_chat_completion_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "test-key")
    cfg = coerce_openai_compatible("nous_research", None)

    class _Response:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [{"message": {"content": "pong"}}],
                    "usage": {"prompt_tokens": 3, "completion_tokens": 1},
                }
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

    with patch("urllib.request.urlopen", return_value=_Response()):
        body = openai_compatible_chat_completion(
            cfg,
            model=DEEPSEEK_V4_FLASH_MODEL,
            messages=[{"role": "user", "content": "ping"}],
        )
    assert body["choices"][0]["message"]["content"] == "pong"


async def test_nous_dispatch_writes_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NOUS_API_KEY", "test-key")
    adapter = get_adapter("nous_research", options=None)
    assert isinstance(adapter, NousResearchAdapter)

    class _Response:
        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [{"message": {"content": "wave done"}}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2},
                }
            ).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

    log_path = tmp_path / "attempt.log"
    with patch("urllib.request.urlopen", return_value=_Response()):
        result = await adapter.dispatch(
            {"wave_id": "W2", "model": DEEPSEEK_V4_FLASH_MODEL},
            worktree_path=tmp_path,
            log_path=log_path,
            timeout_s=30,
        )
    assert result.outcome == "done"
    assert result.result_text == "wave done"
    assert log_path.is_file()
