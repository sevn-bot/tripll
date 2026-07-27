"""Per-provider auth preflight at run start (AUTH-01).

Exports:
    AuthPreflightError — raised when a routed provider cannot authenticate.
    check_provider_auth — lightweight availability/auth probe for one backend.
    run_auth_preflight — verify all *providers* before dispatch begins.
"""

from __future__ import annotations

from tripll.adapters import BACKENDS, build_adapter


class AuthPreflightError(RuntimeError):
    """Raised when one or more providers fail the auth preflight."""

    def __init__(self, failures: dict[str, str]) -> None:
        self.failures = dict(failures)
        detail = ", ".join(f"{name}: {msg}" for name, msg in failures.items())
        super().__init__(f"provider auth preflight failed — {detail}")


def check_provider_auth(name: str) -> tuple[bool, str]:
    """Verify *name* can run on this host (binary present + capability gate).

    Args:
        name (str): Backend id (``claude_code``, ``cursor_local``, …).

    Returns:
        tuple[bool, str]: ``(ok, detail)`` — detail explains failures.

    Raises:
        KeyError: When *name* is not a known backend.

    Examples:
        >>> ok, _detail = check_provider_auth("claude_code")
        >>> isinstance(ok, bool)
        True
    """
    if name not in BACKENDS:
        msg = f"unknown backend {name!r}"
        raise KeyError(msg)
    adapter = build_adapter(name)
    caps = adapter.capabilities()
    if not caps.available:
        return False, caps.detail or f"{name} unavailable"
    return True, caps.detail or f"{name} ready"


def run_auth_preflight(providers: set[str]) -> None:
    """Fail fast when any *providers* cannot authenticate.

    Args:
        providers (set[str]): Backend ids referenced by the run graph.

    Raises:
        AuthPreflightError: When any provider fails :func:`check_provider_auth`.

    Examples:
        >>> run_auth_preflight({"claude_code"})  # doctest: +SKIP
    """
    failures: dict[str, str] = {}
    for name in sorted(providers):
        try:
            ok, detail = check_provider_auth(name)
        except KeyError as exc:
            failures[name] = str(exc)
            continue
        if not ok:
            failures[name] = detail
    if failures:
        raise AuthPreflightError(failures)
