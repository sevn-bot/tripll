"""spec-kit-wave scaffold — create a wave-file from the template.

Exports:
    scaffold_wave_file — write ``waves/<slug>-wave-plan.md`` from the template.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from tripll.skw.validate import load_skw_config


def scaffold_wave_file(
    kit_root: Path,
    *,
    slug: str,
    title: str,
    base: str | None = None,
    branch: str | None = None,
) -> Path:
    """Scaffold one wave-file under ``waves/``.

    Args:
        kit_root (Path): Kit root directory.
        slug (str): Short plan slug (filename stem).
        title (str): Display title.
        base (str | None): Diff base ref (``skw.toml`` default when omitted).
        branch (str | None): Feature branch (``feature/<slug>`` when omitted).

    Returns:
        Path: Written wave-file path.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     root = Path(d)
        ...     (root / "wave-plan-template.md").write_text(
        ...         "# {{TITLE}}\\n```toml\\ntitle=\\"t\\"\\nslug=\\"s\\"\\n```\\n",
        ...         encoding="utf-8",
        ...     )
        ...     (root / "scripts").mkdir()
        ...     p = scaffold_wave_file(root, slug="s", title="T", base="main", branch="b")
        ...     p.name.endswith("-wave-plan.md")
        True
    """
    skw = load_skw_config(kit_root)
    resolved_base = base or str(skw.get("base", "origin/main"))
    resolved_branch = branch or f"feature/{slug}"
    out = kit_root / "waves" / f"{slug}-wave-plan.md"
    if out.exists():
        msg = f"Already exists: {out.relative_to(kit_root)}"
        raise FileExistsError(msg)
    template_path = kit_root / "wave-plan-template.md"
    if not template_path.is_file():
        msg = f"template not found: {template_path.name}"
        raise FileNotFoundError(msg)
    text = template_path.read_text(encoding="utf-8")
    replacements = [
        ("Tier-B quality remediation", title),
        ("tier-b-quality", slug),
        ("test-pre", resolved_base),
        ("feature/tier-b-quality", resolved_branch),
        ("{{TITLE}}", title),
        ("{{YYYY-MM-DD}}", str(datetime.now(UTC).date())),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


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
    parser = argparse.ArgumentParser(description="Scaffold a wave-file from wave-plan-template.md.")
    parser.add_argument("slug", help="Plan slug (waves/<slug>-wave-plan.md)")
    parser.add_argument("title", help="Display title")
    parser.add_argument("--base", default=None, help="Diff base ref (skw.toml default)")
    parser.add_argument("--branch", default=None, help="Feature branch (default feature/<slug>)")
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=None,
        help="Kit root directory (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)

    kit_root = args.kit_root
    if kit_root is None:
        kit_root = Path(__file__).resolve().parent
    kit_root = kit_root.resolve()

    try:
        out = scaffold_wave_file(
            kit_root,
            slug=args.slug,
            title=args.title,
            base=args.base,
            branch=args.branch,
        )
    except (FileExistsError, FileNotFoundError) as exc:
        print(f"scaffold.py: {exc}", file=sys.stderr)
        return 1

    print(f"scaffolded {out.relative_to(kit_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
