#!/usr/bin/env python3
"""Build the static ``about-tripll/`` help site from YAML sources + Jinja2 templates.

Module: scripts.build_about_site
Depends: jinja2, pyyaml

Each page is a ``about-tripll/_sources/<slug>.yaml`` file (``title``, ``summary``,
``nav_label``, ``nav_order``, ``body`` HTML) rendered through
``about-tripll/_templates/base.html.j2`` + ``generic.html.j2`` into
``about-tripll/<slug>.html``. Output is deterministic (no timestamps), so ``--check``
can act as a CI drift gate: it fails when committed HTML diverges from the sources.

Exports:
    build_pages — render every source page to an ``{slug: html}`` mapping.
    write_pages — render and write the HTML files; returns the slugs written.
    check_pages — render and compare against on-disk HTML; returns stale slugs.
    main — CLI entry (``--check`` to verify, otherwise write).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parents[1]
ABOUT = ROOT / "about-tripll"
SOURCES = ABOUT / "_sources"
TEMPLATES = ABOUT / "_templates"


def _load_sources() -> list[dict[str, Any]]:
    """Load and validate every page source YAML.

    Returns:
        list[dict[str, Any]]: Page dicts, each with an injected ``slug`` key,
        sorted by ``nav_order`` then ``slug``.

    Raises:
        ValueError: When a source file is missing a required field.

    Examples:
        >>> pages = _load_sources()
        >>> all("slug" in p and "title" in p for p in pages)
        True
    """
    pages: list[dict[str, Any]] = []
    for path in sorted(SOURCES.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for field in ("title", "nav_label", "body"):
            if field not in data:
                msg = f"{path.name}: missing required field '{field}'"
                raise ValueError(msg)
        data["slug"] = path.stem
        data.setdefault("nav_order", 100)
        data.setdefault("summary", "")
        pages.append(data)
    pages.sort(key=lambda p: (p["nav_order"], p["slug"]))
    return pages


def _environment() -> Environment:
    """Build the Jinja2 environment bound to the templates directory.

    Returns:
        Environment: Autoescaping Jinja2 environment.

    Examples:
        >>> env = _environment()
        >>> env.get_template("base.html.j2") is not None
        True
    """
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


def build_pages() -> dict[str, str]:
    """Render every source page to HTML.

    Returns:
        dict[str, str]: Mapping of ``slug`` to rendered HTML.

    Examples:
        >>> html = build_pages()
        >>> "index" in html and html["index"].startswith("<!DOCTYPE html>")
        True
    """
    pages = _load_sources()
    nav_pages = [(f"{p['slug']}.html", p["nav_label"]) for p in pages]
    env = _environment()
    template = env.get_template("generic.html.j2")
    rendered: dict[str, str] = {}
    for page in pages:
        html = template.render(
            slug=page["slug"],
            title=page["title"],
            summary=page["summary"],
            body_html=page["body"],
            nav_pages=nav_pages,
        )
        rendered[page["slug"]] = html.rstrip("\n") + "\n"
    return rendered


def write_pages() -> list[str]:
    """Render and write all HTML files into ``about-tripll/``.

    Returns:
        list[str]: Slugs written, in nav order.

    Examples:
        >>> slugs = write_pages()
        >>> "index" in slugs
        True
    """
    rendered = build_pages()
    for slug, html in rendered.items():
        (ABOUT / f"{slug}.html").write_text(html, encoding="utf-8")
    return list(rendered)


def check_pages() -> list[str]:
    """Compare rendered HTML against the committed files.

    Returns:
        list[str]: Slugs whose on-disk HTML is missing or stale.

    Examples:
        >>> isinstance(check_pages(), list)
        True
    """
    rendered = build_pages()
    stale: list[str] = []
    for slug, html in rendered.items():
        target = ABOUT / f"{slug}.html"
        if not target.exists() or target.read_text(encoding="utf-8") != html:
            stale.append(slug)
    return stale


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for building or checking the site.

    Args:
        argv (list[str] | None): Arguments (defaults to ``sys.argv[1:]``).

    Returns:
        int: 0 on success; 1 when ``--check`` finds stale HTML.

    Examples:
        >>> import contextlib, io
        >>> with contextlib.redirect_stdout(io.StringIO()):
        ...     rc = main(["--check"])
        >>> rc in (0, 1)
        True
    """
    parser = argparse.ArgumentParser(description="Build the about-tripll help site.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if committed HTML diverges from sources (CI drift gate).",
    )
    args = parser.parse_args(argv)

    if args.check:
        stale = check_pages()
        if stale:
            print(
                "about-tripll: stale HTML — run `make about-site`:\n  "
                + "\n  ".join(f"{s}.html" for s in stale),
                file=sys.stderr,
            )
            return 1
        print("about-tripll: site is up to date.")
        return 0

    slugs = write_pages()
    print(f"about-tripll: wrote {len(slugs)} page(s): {', '.join(slugs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
