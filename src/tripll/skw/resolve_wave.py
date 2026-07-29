"""Resolve wave ids and roles from wave-files (stdlib only).

Exports:
    agent_for_role — map wave role → agent id.
    wave_roles — map wave id → role string from TOML ``[[waves]]`` rows.
    test_author_ids — list wave ids with ``role = test-author``.
    resolve_test_author_id — sole test-author id or raise.
    wave_role — role for one wave id.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from tripll.skw.validate import extract_toml_block
from tripll.skw.wave_model import WavePlan

__all__: list[str] = [
    "agent_for_role",
    "load_wave_data",
    "resolve_test_author_id",
    "test_author_ids",
    "wave_role",
    "wave_roles",
]

_ROLE_TO_AGENT = {
    "test-author": "test-creator",
    "impl": "wave-runner",
}


def agent_for_role(role: str) -> str:
    """Map a wave ``role`` string to the agent id that executes it.

    Args:
        role (str): Wave role (``impl`` or ``test-author``).

    Returns:
        str: Agent id (``wave-runner`` or ``test-creator``).

    Examples:
        >>> agent_for_role("test-author")
        'test-creator'
        >>> agent_for_role("impl")
        'wave-runner'
    """
    return _ROLE_TO_AGENT.get(role, "wave-runner")


def wave_roles(data: dict[str, Any]) -> dict[str, str]:
    """Return wave id → role from parsed TOML.

    Args:
        data (dict): Parsed wave-file TOML contract.

    Returns:
        dict[str, str]: Map of wave id to role (default ``impl``).

    Examples:
        >>> wave_roles({"waves": [{"id": "W0", "role": "test-author"}]})
        {'W0': 'test-author'}
    """
    return {plan.id: plan.role for plan in WavePlan.from_wave_data(data)}


def test_author_ids(data: dict[str, Any]) -> list[str]:
    """Return wave ids with ``role = test-author``.

    Args:
        data (dict): Parsed wave-file TOML contract.

    Returns:
        list[str]: Matching wave ids in declaration order.

    Examples:
        >>> test_author_ids({"waves": [{"id": "W1", "role": "test-author"}]})
        ['W1']
    """
    return [wid for wid, role in wave_roles(data).items() if role == "test-author"]


def resolve_test_author_id(data: dict[str, Any]) -> str:
    """Return the sole test-author wave id.

    Args:
        data (dict): Parsed wave-file TOML contract.

    Returns:
        str: The only test-author wave id.

    Raises:
        ValueError: When zero or more than one test-author wave exists.

    Examples:
        >>> resolve_test_author_id({"waves": [{"id": "W1", "role": "test-author"}]})
        'W1'
    """
    ids = test_author_ids(data)
    if not ids:
        msg = "no test-author wave in wave-file (role = test-author on exactly one [[waves]] row)"
        raise ValueError(msg)
    if len(ids) > 1:
        msg = f"multiple test-author waves: {', '.join(ids)} — use WAVE_ID= to pick one"
        raise ValueError(msg)
    return ids[0]


def wave_role(data: dict[str, Any], wave_id: str) -> str:
    """Return the role for *wave_id*.

    Args:
        data (dict): Parsed wave-file TOML contract.
        wave_id (str): Target wave id.

    Returns:
        str: Role string (``impl`` when omitted).

    Raises:
        ValueError: When *wave_id* is unknown.

    Examples:
        >>> wave_role({"waves": [{"id": "W0", "role": "impl"}]}, "W0")
        'impl'
    """
    roles = wave_roles(data)
    if wave_id not in roles:
        msg = f"unknown wave id {wave_id!r} (known: {', '.join(sorted(roles)) or '(none)'})"
        raise ValueError(msg)
    return roles[wave_id]


def load_wave_data(wave_path: Path) -> dict[str, Any]:
    """Parse TOML contract from *wave_path*.

    Args:
        wave_path (Path): Path to wave markdown file.

    Returns:
        dict: Parsed TOML block.

    Raises:
        ValueError: On parse or schema errors.
    """
    text = wave_path.read_text(encoding="utf-8")
    data, err = extract_toml_block(text)
    if err or data is None:
        msg = err or "empty TOML block"
        raise ValueError(msg)
    return data


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv (list[str] | None): Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        int: Exit code (0 = success, 1 = error).

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(description="Resolve wave ids and roles from a wave-file.")
    parser.add_argument("wave_file", type=Path, help="Path to the wave markdown file")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--test-author-id",
        action="store_true",
        help="Print sole test-author wave id (error if 0 or >1)",
    )
    group.add_argument("--role", metavar="WAVE_ID", help="Print role for WAVE_ID")
    group.add_argument(
        "--validate-impl",
        metavar="WAVE_ID",
        help="Exit 0 for impl waves; exit 1 for test-author with hint",
    )
    args = parser.parse_args(argv)

    try:
        data = load_wave_data(args.wave_file.resolve())
    except ValueError as exc:
        print(f"resolve_wave.py: {exc}", file=sys.stderr)
        return 1

    try:
        if args.test_author_id:
            print(resolve_test_author_id(data))
        elif args.role is not None:
            print(wave_role(data, args.role))
        elif args.validate_impl is not None:
            role = wave_role(data, args.validate_impl)
            if role == "test-author":
                print(
                    f"resolve_wave.py: wave {args.validate_impl!r} has role=test-author; "
                    "use uv run skw agent-run --stage run on the test-author wave instead of wave-runner",
                    file=sys.stderr,
                )
                return 1
    except ValueError as exc:
        print(f"resolve_wave.py: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
