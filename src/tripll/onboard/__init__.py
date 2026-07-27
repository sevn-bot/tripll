"""Onboarding helpers — setup, doctor, init, next-step hints (W13+).

Exports:
    compute_next_step — next tripll command from plan checkbox state.
    run_brownfield_init — brownfield ``tripll init`` orchestration.
"""

from __future__ import annotations

from tripll.onboard.brownfield import run_brownfield_init
from tripll.onboard.greenfield import new_project
from tripll.onboard.nextstep import compute_next_step

__all__: list[str] = ["compute_next_step", "new_project", "run_brownfield_init"]
