"""tripll.parse.markdown — markdown table & heading helpers for parsers.

Small, dependency-free helpers shared by the Mode A and Mode B parsers:
locate a pipe-table by a header predicate and yield its rows as cell lists,
and strip markdown emphasis/backticks from a cell.

Exports:
    strip_md — remove ``*`` and backtick emphasis from a string.
    split_row — split a markdown table row into trimmed cells.
    slice_section — body of the first ``##`` section matching a substring.
    find_table_rows — yield cell-lists for the first table whose header
        matches a keyword predicate.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

_EMPHASIS = re.compile(r"[*`]")


def strip_md(text: str) -> str:
    """Strip markdown emphasis (``*``) and backticks from *text*.

    Args:
        text (str): Raw cell text.

    Returns:
        str: Cleaned, trimmed text.

    Examples:
        >>> strip_md("**Telemetry** `lane`")
        'Telemetry lane'
    """
    return _EMPHASIS.sub("", text).strip()


def split_row(line: str) -> list[str]:
    """Split a markdown table row into trimmed cell strings.

    Args:
        line (str): A single ``| a | b | c |`` table row.

    Returns:
        list[str]: Trimmed cell contents (outer pipes removed).

    Examples:
        >>> split_row("| 1 | foo | bar |")
        ['1', 'foo', 'bar']
    """
    return [c.strip() for c in line.strip().strip("|").split("|")]


def slice_section(text: str, heading_substr: str) -> str:
    """Return the body of the first ``##`` section whose heading contains *heading_substr*.

    Args:
        text (str): Markdown document.
        heading_substr (str): Substring matched against ``##`` headings.

    Returns:
        str: Section body without the heading line.

    Examples:
        >>> slice_section("## Foo bar\\n\\nhello\\n", "Foo")
        'hello'
    """
    lines = text.splitlines()
    out: list[str] = []
    in_section = False
    for line in lines:
        if re.match(r"^##\s+", line):
            if in_section:
                break
            if heading_substr in line:
                in_section = True
                continue
        if in_section:
            out.append(line)
    return "\n".join(out)


def find_table_rows(text: str, header_keywords: Iterable[str]) -> list[list[str]]:
    """Return the data rows of the first table whose header contains all keywords.

    Scans *text* line by line. A header line is one that starts a pipe-table
    and contains every keyword in *header_keywords*. Subsequent lines until a
    blank line or a non-pipe line are returned as cell-lists, skipping the
    ``|---|`` separator.

    Args:
        text (str): Markdown document text.
        header_keywords (Iterable[str]): Substrings that must all appear in the
            header row (case-sensitive).

    Returns:
        list[list[str]]: One cell-list per data row; empty if no table matches.

    Examples:
        >>> md = "| # | Plan |\\n|---|------|\\n| 1 | a |\\n| 2 | b |\\n"
        >>> find_table_rows(md, ["#", "Plan"])
        [['1', 'a'], ['2', 'b']]
    """
    keywords = list(header_keywords)
    rows: list[list[str]] = []
    in_table = False
    for line in text.splitlines():
        if not in_table:
            if all(k in line for k in keywords) and "|" in line:
                in_table = True
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("|--"):
            if not stripped:
                break
            continue
        if not stripped.startswith("|"):
            break
        rows.append(split_row(line))
    return rows
