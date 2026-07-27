"""tripll.plan_paths — normalize and validate plan file path references.

Rewrites in-repo markdown and backtick path refs to repo-root-relative form
(D1) and collects external upload parent directories for ``--add-dir`` (D3).

Exports:
    normalize_plan_refs — rewrite in-repo refs; return external parent dirs.
    find_unresolved_refs — list in-repo refs that do not resolve under *repo_root*.
    extract_planned_creates — paths listed in ``[pipeline] creates`` (planned-new exempt).
    validate_plan — read a plan file and return dead in-repo refs.
    suggest_plan_ref_fix — repo-root-relative rewrite for a dead ref string.
    format_plan_ref_errors — UX lines ``plan → ref (try: fix)`` for dead refs.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from tripll.skw.validate import extract_toml_block

_MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def _split_anchor(ref: str) -> tuple[str, str]:
    """Split *ref* into path and ``#`` anchor suffix."""
    if "#" in ref:
        path, anchor = ref.split("#", 1)
        return path, f"#{anchor}"
    return ref, ""


def _is_external_url(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith(("http://", "https://", "mailto:"))


def _is_anchor_token(path: str) -> bool:
    """Return True for tokens like ``foo.py:bar`` with no path separator."""
    base = path.split("#", 1)[0]
    return "/" not in base and not base.startswith("/")


def _looks_like_path(token: str) -> bool:
    token = token.strip()
    if not token or _is_external_url(token):
        return False
    if token.startswith("#"):
        return False
    path_part, _ = _split_anchor(token)
    if _is_anchor_token(path_part):
        return False
    return "/" in path_part or path_part.startswith("/")


def _collapse_dotdot(path_part: str) -> str:
    """Strip leading ``./`` and ``../`` prefixes, returning repo-root-relative tail."""
    parts = list(PurePosixPath(path_part).parts)
    while parts and parts[0] in {".", ".."}:
        parts.pop(0)
    return "/".join(parts)


_OPTIONAL_GATE_PREFIXES = ("docs/", "reports/")


def extract_planned_creates(text: str) -> frozenset[str]:
    """Return repo-root-relative paths listed in ``[pipeline] creates``.

    Args:
        text (str): Full plan markdown body.

    Returns:
        frozenset[str]: Planned-new paths exempt from validate-plan gating.

    Examples:
        >>> extract_planned_creates('[pipeline]\\ncreates = ["src/a.py"]\\n')
        frozenset({'src/a.py'})
    """
    data, _err = extract_toml_block(text)
    if not data:
        return frozenset()
    pipeline = data.get("pipeline")
    if not isinstance(pipeline, dict):
        return frozenset()
    creates = pipeline.get("creates") or []
    if not isinstance(creates, list):
        return frozenset()
    return frozenset(str(item) for item in creates)


def _skip_gate_ref(path_part: str, *, planned_creates: frozenset[str] | None = None) -> bool:
    """Return True when *path_part* is exempt from validate-plan dead-ref gating."""
    collapsed = _collapse_dotdot(path_part.split("#", 1)[0])
    return bool(
        any(collapsed.startswith(prefix) for prefix in _OPTIONAL_GATE_PREFIXES)
        or (planned_creates and collapsed in planned_creates)
    )


def _plan_link_base_dirs(plan_path: Path, repo_root: Path) -> list[Path]:
    """Return candidate base directories for resolving plan-relative links."""
    root = repo_root.resolve()
    dirs: list[Path] = [plan_path.parent.resolve()]
    set_name = plan_path.parent.name
    canonical = root / "plan" / set_name
    if canonical.is_dir():
        resolved = canonical.resolve()
        if resolved not in dirs:
            dirs.append(resolved)
    else:
        plan_root = root / "plan"
        if plan_root.is_dir():
            for candidate in sorted(plan_root.glob("*/")):
                if (candidate / plan_path.name).is_file():
                    resolved = candidate.resolve()
                    if resolved not in dirs:
                        dirs.append(resolved)
    return dirs


def _resolve_in_repo_from_bases(
    path_part: str,
    repo_root: Path,
    base_dirs: list[Path],
) -> Path | None:
    """Try *path_part* against each base dir, then repo-root fallbacks."""
    for base in base_dirs:
        resolved = _resolve_in_repo(path_part, repo_root, base_dir=base)
        if resolved is not None and resolved.exists():
            return resolved
    resolved = _resolve_in_repo(path_part, repo_root)
    if resolved is not None and resolved.exists():
        return resolved
    return None


def _resolve_in_repo(
    path_part: str,
    repo_root: Path,
    *,
    base_dir: Path | None = None,
) -> Path | None:
    """Resolve *path_part* to an absolute path under *repo_root*, or ``None``."""
    root = repo_root.resolve()
    if path_part.startswith((".", "..")) and base_dir is not None:
        candidate = (base_dir / path_part).resolve()
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            pass
    if path_part.startswith("/"):
        candidate = Path(path_part).expanduser().resolve()
    else:
        direct = (root / path_part).resolve()
        try:
            direct.relative_to(root)
            return direct
        except ValueError:
            collapsed = _collapse_dotdot(path_part)
            if not collapsed:
                return None
            candidate = (root / collapsed).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    return candidate


def _is_external_absolute(path_part: str, repo_root: Path) -> bool:
    if not path_part.startswith("/"):
        return False
    resolved = Path(path_part).expanduser().resolve()
    try:
        resolved.relative_to(repo_root.resolve())
    except ValueError:
        return True
    return False


def _to_repo_relative(path_part: str, repo_root: Path) -> str:
    """Rewrite in-repo *path_part* to repo-root-relative form."""
    resolved = _resolve_in_repo(path_part, repo_root)
    if resolved is None:
        collapsed = _collapse_dotdot(path_part)
        return collapsed or path_part
    rel = resolved.relative_to(repo_root.resolve())
    return rel.as_posix()


def _external_parent_dir(path_part: str) -> str:
    p = Path(path_part).expanduser()
    parent = p.parent if p.suffix else p
    return str(parent.resolve())


def _rewrite_ref(ref: str, repo_root: Path, external_dirs: set[str]) -> str:
    path_part, anchor = _split_anchor(ref.strip())
    if not path_part or _is_external_url(path_part) or _is_anchor_token(path_part):
        return ref
    if _is_external_absolute(path_part, repo_root):
        external_dirs.add(_external_parent_dir(path_part))
        return ref
    normalized = _to_repo_relative(path_part, repo_root)
    if normalized == path_part:
        return ref
    return normalized + anchor


def _iter_refs(text: str, *, backticks: bool) -> list[tuple[int, int, str]]:
    """Return ``(start, end, ref)`` spans for markdown links and/or backticks."""
    spans: list[tuple[int, int, str]] = []
    for match in _MD_LINK_RE.finditer(text):
        spans.append((match.start(1), match.end(1), match.group(1)))
    if backticks:
        for match in _BACKTICK_RE.finditer(text):
            token = match.group(1)
            if _looks_like_path(token):
                spans.append((match.start(1), match.end(1), token))
    spans.sort(key=lambda item: item[0])
    return spans


def normalize_plan_refs(text: str, repo_root: Path) -> tuple[str, list[str]]:
    """Rewrite in-repo refs to repo-root-relative; return external parent dirs.

    Pure function — does not write to the filesystem.

    Args:
        text (str): Plan markdown body.
        repo_root (Path): Repository root (worktree checkout).

    Returns:
        tuple[str, list[str]]: ``(normalized_text, external_parent_dirs)``.

    Examples:
        >>> from pathlib import Path
        >>> body = "See [spec](../../specs/x.md) and `specs/y.md`."
        >>> new, ext = normalize_plan_refs(body, Path("/repo"))
        >>> "../../specs/x.md" not in new
        True
        >>> ext == []
        True
    """
    external_dirs: set[str] = set()
    spans = _iter_refs(text, backticks=True)
    if not spans:
        return text, []
    parts: list[str] = []
    last = 0
    for start, end, ref in spans:
        parts.append(text[last:start])
        parts.append(_rewrite_ref(ref, repo_root, external_dirs))
        last = end
    parts.append(text[last:])
    dirs = sorted(external_dirs)
    return "".join(parts), dirs


def find_unresolved_refs(
    text: str,
    repo_root: Path,
    *,
    plan_path: Path | None = None,
    planned_creates: frozenset[str] | None = None,
) -> list[str]:
    """Return in-repo markdown link refs in *text* that do not resolve.

    Only ``](path)`` link targets are checked (not scope-table backticks).

    Args:
        text (str): Plan markdown body.
        repo_root (Path): Repository root (worktree checkout).
        plan_path (Path | None): Plan file path; used to resolve ``../`` links
            from both the staged location and ``plan/<set>/`` when present.

    Returns:
        list[str]: Dead ref strings (empty when all in-repo refs resolve).

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     root = Path(d)
        ...     (root / "specs").mkdir()
        ...     (root / "specs" / "ok.md").write_text("ok")
        ...     dead = find_unresolved_refs("[x](../../specs/missing.md)", root)
        ...     dead == ["../../specs/missing.md"]
        True
    """
    root = repo_root.resolve()
    base_dirs = _plan_link_base_dirs(plan_path, root) if plan_path is not None else []
    dead: list[str] = []
    seen: set[str] = set()
    for _start, _end, ref in _iter_refs(text, backticks=False):
        raw = ref.strip()
        if raw in seen:
            continue
        path_part, _anchor = _split_anchor(raw)
        if not path_part or _is_external_url(path_part) or _is_anchor_token(path_part):
            continue
        if _is_external_absolute(path_part, root):
            continue
        if _skip_gate_ref(path_part, planned_creates=planned_creates):
            continue
        if base_dirs:
            resolved = _resolve_in_repo_from_bases(path_part, root, base_dirs)
        else:
            resolved = _resolve_in_repo(path_part, root)
            if resolved is not None and not resolved.exists():
                resolved = None
        if resolved is None:
            seen.add(raw)
            dead.append(raw)
    return dead


def suggest_plan_ref_fix(
    ref: str,
    repo_root: Path,
    *,
    plan_path: Path | None = None,
) -> str:
    """Return a repo-root-relative rewrite suggestion for a dead in-repo *ref*.

    Args:
        ref (str): Dead reference string from :func:`find_unresolved_refs`.
        repo_root (Path): Repository root (worktree checkout).
        plan_path (Path | None): Plan file for multi-base ``../`` resolution.

    Returns:
        str: Suggested fix (usually repo-root-relative path).

    Examples:
        >>> from pathlib import Path
        >>> suggest_plan_ref_fix("../../specs/x.md", Path("/repo"))
        'specs/x.md'
    """
    path_part, anchor = _split_anchor(ref.strip())
    if not path_part or _is_external_url(path_part) or _is_anchor_token(path_part):
        return ref
    if _is_external_absolute(path_part, repo_root):
        return ref
    base_dirs = _plan_link_base_dirs(plan_path, repo_root) if plan_path else []
    resolved = (
        _resolve_in_repo_from_bases(path_part, repo_root, base_dirs)
        if base_dirs
        else _resolve_in_repo(path_part, repo_root)
    )
    if resolved is not None:
        rel = resolved.relative_to(repo_root.resolve())
        return rel.as_posix() + anchor
    normalized = _to_repo_relative(path_part, repo_root)
    return normalized + anchor


def format_plan_ref_errors(
    plan_path: Path,
    dead_refs: list[str],
    repo_root: Path,
) -> list[str]:
    """Format dead refs as ``plan → ref (try: fix)`` lines (W0.3 UX).

    Args:
        plan_path (Path): Wave-plan markdown file.
        dead_refs (list[str]): Dead ref strings from :func:`validate_plan`.
        repo_root (Path): Repository root (worktree checkout).

    Returns:
        list[str]: One formatted line per dead ref.

    Examples:
        >>> from pathlib import Path
        >>> lines = format_plan_ref_errors(
        ...     Path("plan/x-wave-plan.md"),
        ...     ["../../specs/nope.md"],
        ...     Path("/repo"),
        ... )
        >>> lines[0].startswith("plan/x-wave-plan.md → ")
        True
    """
    display = plan_path.as_posix()
    return [
        f"{display} → {ref} (try: {suggest_plan_ref_fix(ref, repo_root, plan_path=plan_path)})"
        for ref in dead_refs
    ]


def validate_plan(plan_path: Path, repo_root: Path) -> list[str]:
    """Read *plan_path* and return dead in-repo ref strings.

    Args:
        plan_path (Path): Wave-plan markdown file.
        repo_root (Path): Repository root (worktree checkout).

    Returns:
        list[str]: Dead refs (empty when the plan is valid).

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     root = Path(d)
        ...     plan = root / "plan.md"
        ...     plan.write_text("[bad](../../specs/nope.md)")
        ...     validate_plan(plan, root) == ["../../specs/nope.md"]
        True
    """
    text = plan_path.read_text(encoding="utf-8")
    planned = extract_planned_creates(text)
    return find_unresolved_refs(
        text,
        repo_root,
        plan_path=plan_path.resolve(),
        planned_creates=planned,
    )
