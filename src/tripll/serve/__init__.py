"""Serve layer — brief packing and handoff contracts."""

from tripll.serve.handoff import (
    HANDOFF_FIELDS,
    HANDOFF_GOVERNING_RULE,
    build_handoff,
    format_handoff_block,
    validate_handoff,
)

__all__ = [
    "HANDOFF_FIELDS",
    "HANDOFF_GOVERNING_RULE",
    "build_handoff",
    "format_handoff_block",
    "validate_handoff",
]
