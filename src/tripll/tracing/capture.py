"""Prompt/completion capture policy (R21).

Exports:
    CaptureMode — ``off`` | ``shape`` | ``full``.
    DEFAULT_CAPTURE — default policy (``shape``).
    parse_capture_mode — parse and validate a capture string.
    shape_capture_value — shape or drop prompt-like attribute values.
"""

from __future__ import annotations

from typing import Any, Literal

CaptureMode = Literal["off", "shape", "full"]
DEFAULT_CAPTURE: CaptureMode = "shape"
VALID_CAPTURE: frozenset[str] = frozenset({"off", "shape", "full"})


def parse_capture_mode(value: str | None) -> CaptureMode:
    """Parse a capture policy string.

    Args:
        value (str | None): Raw config value.

    Returns:
        CaptureMode: Normalised mode; defaults to :data:`DEFAULT_CAPTURE`.

    Raises:
        ValueError: When *value* is not a known mode.
    """
    if value is None or not str(value).strip():
        return DEFAULT_CAPTURE
    mode = str(value).strip().lower()
    if mode not in VALID_CAPTURE:
        raise ValueError(f"invalid tracing.capture={value!r} — expected off|shape|full")
    return mode  # type: ignore[return-value]


def _shape_message(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        role = value.get("role")
        content = value.get("content")
        blocks: list[str] = []
        chars = 0
        if isinstance(content, str):
            chars = len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    blocks.append(str(block.get("type", "block")))
                    text = block.get("text")
                    if isinstance(text, str):
                        chars += len(text)
                else:
                    blocks.append(type(block).__name__)
        return {"role": role, "block_types": blocks, "char_count": chars}
    if isinstance(value, list):
        return {"messages": [_shape_message(item) for item in value[:32]], "count": len(value)}
    if isinstance(value, str):
        return {"char_count": len(value)}
    return {"type": type(value).__name__}


def shape_capture_value(key: str, value: Any, *, mode: CaptureMode) -> Any:
    """Apply the capture policy to a prompt-like attribute.

    Args:
        key (str): Attribute name.
        value (Any): Raw attribute value.
        mode (CaptureMode): Active capture policy.

    Returns:
        Any: Shaped value, ``None`` when dropped, or the original for non-prompt keys.
    """
    prompt_keys = frozenset(
        {
            "prompt",
            "completion",
            "messages",
            "input",
            "output",
            "system",
            "user",
            "assistant",
        }
    )
    lower = key.lower()
    is_promptish = lower in prompt_keys or any(token in lower for token in ("prompt", "message"))
    if not is_promptish:
        return value
    if mode == "off":
        return None
    if mode == "full":
        return value
    return _shape_message(value)
