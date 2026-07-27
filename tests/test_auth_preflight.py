"""Auth preflight — fail before dispatch when providers unavailable (AUTH-01)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from tripll.adapters.auth_preflight import AuthPreflightError, run_auth_preflight


def test_run_auth_preflight_raises_when_provider_unavailable() -> None:
    with (
        patch(
            "tripll.adapters.auth_preflight.check_provider_auth",
            return_value=(False, "binary missing"),
        ),
        pytest.raises(AuthPreflightError) as exc,
    ):
        run_auth_preflight({"claude_code"})
    assert "claude_code" in exc.value.failures


def test_run_auth_preflight_passes_when_all_providers_ready() -> None:
    with patch(
        "tripll.adapters.auth_preflight.check_provider_auth",
        return_value=(True, "ready"),
    ):
        run_auth_preflight({"cursor_local", "claude_code"})
