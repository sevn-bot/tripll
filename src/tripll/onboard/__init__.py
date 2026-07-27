"""Onboarding helpers — setup, doctor, next-step hints (W13+).

Exports:
    compute_next_step — next tripll command from plan checkbox state.
"""

from __future__ import annotations

from tripll.onboard.nextstep import compute_next_step

__all__: list[str] = ["compute_next_step"]
