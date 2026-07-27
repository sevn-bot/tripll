"""Wave plan model — single parse path for ``[[waves]]`` TOML rows.

Exports:
    WavePlan — dataclass for one compiled wave row.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__: list[str] = ["WavePlan"]


@dataclass
class WavePlan:
    """One wave row from a wave-file TOML contract."""

    id: str
    title: str
    role: str = "impl"
    depends_on: list[str] = field(default_factory=list)
    verify: list[str] = field(default_factory=list)
    review_gate: bool = False
    effort: str = "M"

    @classmethod
    def from_wave_data(cls, data: dict[str, Any]) -> list[WavePlan]:
        """Parse ``[[waves]]`` rows from parsed TOML *data*.

        Args:
            data (dict[str, Any]): Parsed wave-file TOML contract.

        Returns:
            list[WavePlan]: Wave rows in declaration order (invalid rows skipped).

        Examples:
            >>> WavePlan.from_wave_data({"waves": [{"id": "W0", "title": "t"}]})
            [WavePlan(id='W0', title='t', role='impl', depends_on=[], verify=[], review_gate=False, effort='M')]
        """
        waves_raw = data.get("waves", [])
        if not isinstance(waves_raw, list):
            return []

        plans: list[WavePlan] = []
        for wave in waves_raw:
            if not isinstance(wave, dict):
                continue
            wid = wave.get("id")
            if not isinstance(wid, str) or not wid.strip():
                continue
            title = wave.get("title", wid)
            deps = wave.get("depends_on", [])
            if deps is None:
                deps = []
            dep_ids = [d for d in deps if isinstance(d, str)] if isinstance(deps, list) else []
            verify = wave.get("verify", [])
            if verify is None:
                verify = []
            verify_list = (
                [v for v in verify if isinstance(v, str)] if isinstance(verify, list) else []
            )
            role = wave.get("role", "impl")
            effort = wave.get("effort", "M")
            review_gate = wave.get("review_gate")
            plans.append(
                cls(
                    id=wid,
                    title=title if isinstance(title, str) else wid,
                    role=role if isinstance(role, str) else "impl",
                    depends_on=dep_ids,
                    verify=verify_list,
                    review_gate=bool(review_gate) if isinstance(review_gate, bool) else False,
                    effort=effort if isinstance(effort, str) else "M",
                )
            )
        return plans
