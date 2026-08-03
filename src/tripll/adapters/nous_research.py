"""tripll.adapters.nous_research — Nous Research OpenAI-compatible backend (#76).

Uses the Nous inference gateway (``https://inference-api.nousresearch.com/v1``) with
stdlib HTTP — no Nous or OpenAI SDK dependency. Credentials come from ``NOUS_API_KEY``
(R24). Agentic wave dispatch is limited to single-turn chat completions; full tool-loop
dispatch remains on CLI backends.

Exports:
    NousResearchAdapter — OpenAI-compatible HTTP adapter for Nous Research.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from tripll.adapters.base import AdapterCapabilities, AgentAdapter, DispatchResult
from tripll.brief import render_dispatch_prompt
from tripll.config import load_config, resolve_openai_compatible
from tripll.config.providers import (
    OpenAiCompatibleProviderConfig,
    openai_compatible_chat_completion,
    resolve_api_key,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path


class NousResearchAdapter(AgentAdapter):
    """Nous Research adapter — OpenAI-compatible HTTP chat completions.

    Args:
        model (str | None): Model override; defaults to config ``default_model``.

    Examples:
        >>> NousResearchAdapter().name
        'nous_research'
    """

    name = "nous_research"

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model

    def _endpoint_cfg(self) -> OpenAiCompatibleProviderConfig:
        cfg = load_config()
        return resolve_openai_compatible(cfg, self.name)

    def capabilities(self) -> AdapterCapabilities:
        """Return availability based on ``NOUS_API_KEY`` (or configured env var).

        Returns:
            AdapterCapabilities: ``available`` when the API key env var is set.

        Examples:
            >>> isinstance(NousResearchAdapter().capabilities().available, bool)
            True
        """
        endpoint = self._endpoint_cfg()
        key = resolve_api_key(endpoint)
        return AdapterCapabilities(
            backend=self.name,
            available=key is not None,
            detail=(
                f"{endpoint.api_key_env} set — {endpoint.default_model} via {endpoint.base_url}"
                if key
                else f"export {endpoint.api_key_env} (Nous Portal API key) to enable"
            ),
            streaming=False,
        )

    def build_argv(self, brief: dict[str, object], worktree_path: Path) -> list[str]:
        """HTTP dispatch — no subprocess argv.

        Args:
            brief (dict[str, object]): Dispatch brief (unused for argv).
            worktree_path (Path): Worktree (unused for HTTP dispatch).

        Returns:
            list[str]: Always empty.

        Examples:
            >>> from pathlib import Path
            >>> NousResearchAdapter().build_argv({}, Path("/wt"))
            []
        """
        return []

    def _resolve_model(self, brief: dict[str, object]) -> str:
        endpoint = self._endpoint_cfg()
        brief_model = brief.get("model")
        if brief_model is not None and str(brief_model).strip():
            return str(brief_model).strip()
        if self.model:
            return self.model
        return endpoint.default_model

    async def dispatch(
        self,
        brief: dict[str, object],
        *,
        worktree_path: Path,
        log_path: Path,
        timeout_s: int,
        log_header: dict[str, object] | None = None,
        on_event: Callable[..., Awaitable[None]] | None = None,
    ) -> DispatchResult:
        """Send one chat completion to the Nous inference gateway."""
        import asyncio
        import time

        from tripll.tracing.spans import trace_span

        del on_event  # HTTP path has no streaming events yet
        header = log_header or {}
        run_id = str(header.get("run_id") or brief.get("run_id") or "")
        node_id = str(header.get("node_id") or brief.get("node_id") or "")
        attempt_id = str(header.get("attempt_id") or "")
        model = self._resolve_model(brief)
        started = time.perf_counter()
        with trace_span(
            "tripll.agent.dispatch",
            run_id=run_id or None,
            node_id=node_id or None,
            attempt_id=attempt_id or None,
            backend=self.name,
            model=model,
            worktree=str(worktree_path),
            timeout_s=timeout_s,
        ) as span_bag:
            caps = self.capabilities()
            if not caps.available:
                result = DispatchResult(
                    outcome="failed",
                    result_text=caps.detail,
                    argv=[],
                )
                span_bag.update(
                    outcome=result.outcome,
                    duration_s=time.perf_counter() - started,
                    stop_reason="backend_unavailable",
                )
                return result

            endpoint = self._endpoint_cfg()
            prompt = render_dispatch_prompt(brief)
            messages = [{"role": "user", "content": prompt}]

            try:
                response = await asyncio.to_thread(
                    openai_compatible_chat_completion,
                    endpoint,
                    model=model,
                    messages=messages,
                    timeout_s=float(timeout_s),
                )
            except (RuntimeError, TypeError, json.JSONDecodeError) as exc:
                result = DispatchResult(
                    outcome="failed",
                    result_text=str(exc),
                    argv=[],
                    log_path=str(log_path),
                )
                span_bag.update(
                    outcome=result.outcome,
                    duration_s=time.perf_counter() - started,
                    stop_reason=str(exc),
                )
                return result

            log_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                log_path.write_text,
                json.dumps(response, indent=2),
                encoding="utf-8",
            )

            choices = response.get("choices")
            text = ""
            if isinstance(choices, list) and choices:
                first = choices[0]
                if isinstance(first, dict):
                    message = first.get("message")
                    if isinstance(message, dict):
                        text = str(message.get("content") or "")

            usage_raw = response.get("usage")
            input_tokens: int | None = None
            output_tokens: int | None = None
            if isinstance(usage_raw, dict):
                in_raw = usage_raw.get("prompt_tokens")
                out_raw = usage_raw.get("completion_tokens")
                input_tokens = int(in_raw) if isinstance(in_raw, int) else None
                output_tokens = int(out_raw) if isinstance(out_raw, int) else None

            result = DispatchResult(
                outcome="done" if text else "failed",
                result_text=text or "empty completion from Nous API",
                returncode=0 if text else 1,
                log_path=str(log_path),
                argv=[],
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            span_bag.update(
                outcome=result.outcome,
                returncode=result.returncode,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                duration_s=time.perf_counter() - started,
            )
            return result
