"""Export rejected findings to ``.pullfrog/learnings.md`` (D13)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def export_learnings(
    findings: list[dict[str, Any]],
    *,
    path: Path | str,
) -> Path:
    """Write rejected findings with rationale to ``.pullfrog/learnings.md``."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rejected = [f for f in findings if f.get("state") == "rejected"]
    lines = [
        "# pullfrog learnings",
        "",
        "Findings marked **rejected** by the triager — pullfrog should not re-raise these.",
        "",
    ]
    if not rejected:
        lines.append("_No rejected findings yet._")
    else:
        for finding in rejected:
            rule_id = finding.get("rule_id") or "unknown"
            rationale = finding.get("rationale") or finding.get("message_raw") or ""
            lines.append(f"## {rule_id}")
            lines.append("")
            lines.append("- **state:** rejected")
            if finding.get("file"):
                lines.append(f"- **file:** {finding['file']}")
            lines.append(f"- **rationale:** {rationale}")
            lines.append("")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out
