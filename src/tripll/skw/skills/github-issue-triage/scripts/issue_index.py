#!/usr/bin/env python3
"""Daily-file + index helpers for github-issue-manager.

Usage:
  issue_index.py upsert --index path/to/index.md --entry-json path.json
  issue_index.py remove --index path/to/index.md --number N
  issue_index.py append-daily --dir path/to/github-issues --date YYYY-MM-DD --section-json path.json
  issue_index.py init-index --index path/to/index.md --repo owner/repo

Pure functions operate on markdown text / entry dicts. CLI writes files.

Index upsert is keyed by ``#N``. Daily files are append-only.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

_SECTION_RE = re.compile(
    r"(?ms)^### #(?P<num>\d+) — (?P<title>[^\n]*)\n(?P<body>.*?)(?=^### #\d+ — |\Z)"
)


def empty_index(repo: str = "sevn-bot/sevn") -> str:
    """Return a fresh index.md skeleton."""
    return (
        f"# GitHub issues — index\n\n"
        f"Status: Auto-maintained by github-issue-manager · Repo: `{repo}`\n\n"
        f"Canonical list of **open actionable issues**. Closed issues are removed "
        f"on the next successful sweep. Daily audit logs live beside this file as "
        f"`YYYY-MM-DD.md`.\n\n"
        f"## Open actionable issues\n\n"
    )


def parse_index_entries(text: str) -> dict[int, dict[str, Any]]:
    """Parse ``### #N — title`` sections into a dict keyed by number."""
    entries: dict[int, dict[str, Any]] = {}
    for m in _SECTION_RE.finditer(text):
        num = int(m.group("num"))
        body = m.group("body")
        link = ""
        typ = pri = comp = status = plan = ""
        for line in body.splitlines():
            s = line.strip()
            if s.lower().startswith("- link:"):
                link = s.split(":", 1)[1].strip()
            elif s.lower().startswith("- type"):
                # Type / Priority / Component: …
                rest = s.split(":", 1)[1].strip() if ":" in s else ""
                parts = [p.strip() for p in rest.split("/")]
                if len(parts) >= 1:
                    typ = parts[0]
                if len(parts) >= 2:
                    pri = parts[1]
                if len(parts) >= 3:
                    comp = parts[2]
            elif s.lower().startswith("- status:"):
                status = s.split(":", 1)[1].strip()
            elif s.lower().startswith("- plan:"):
                plan = s.split(":", 1)[1].strip()
        entries[num] = {
            "number": num,
            "title": m.group("title").strip(),
            "url": link,
            "type": typ,
            "priority": pri,
            "component": comp,
            "status": status,
            "plan": plan,
            "raw_body": body,
        }
    return entries


def format_entry(entry: dict[str, Any]) -> str:
    """Format one index section from an entry dict."""
    num = int(entry["number"])
    title = str(entry.get("title") or "").strip() or "(untitled)"
    url = str(entry.get("url") or "").strip() or f"#{num}"
    typ = str(entry.get("type") or "—")
    pri = str(entry.get("priority") or "—")
    comp = str(entry.get("component") or "—")
    status = str(entry.get("status") or "open")
    plan = str(entry.get("plan") or "").strip()
    action = str(entry.get("action") or "").strip()
    lines = [
        f"### #{num} — {title}",
        f"- Link: {url}",
        f"- Type / Priority / Component: {typ} / {pri} / {comp}",
        f"- Status: {status}",
    ]
    if plan:
        lines.append(f"- Plan: {plan}")
    if action:
        lines.append(f"- [ ] {action}")
    lines.append("")
    return "\n".join(lines) + "\n"


def upsert_index(text: str, entry: dict[str, Any]) -> str:
    """Insert or replace the ``### #N`` section for ``entry['number']``.

    Preserves other sections and any preamble before ``## Open actionable issues``.
    Does not rewrite unrelated human-edited content outside the matched section.
    """
    num = int(entry["number"])
    new_block = format_entry(entry)
    # Replace existing section
    pattern = re.compile(rf"(?ms)^### #{num} — [^\n]*\n.*?(?=^### #\d+ — |\Z)")
    if pattern.search(text):
        return pattern.sub(new_block, text, count=1)
    # Append under open section
    if "## Open actionable issues" in text:
        # Insert before end
        return text.rstrip() + "\n\n" + new_block
    return text.rstrip() + "\n\n## Open actionable issues\n\n" + new_block


def remove_from_index(text: str, number: int) -> str:
    """Remove the ``### #N`` section if present."""
    pattern = re.compile(rf"(?ms)^### #{int(number)} — [^\n]*\n.*?(?=^### #\d+ — |\Z)")
    return pattern.sub("", text)


def append_daily_section(
    existing: str,
    *,
    date: str,
    repo: str,
    window: dict[str, Any] | None = None,
    sections: dict[str, Any] | None = None,
) -> str:
    """Append (or create) a daily sweep log.

    If ``existing`` is empty, writes a header. Always appends a new ``## Sweep``
    block so parallel runs do not overwrite prior content.
    """
    sections = sections or {}
    lines: list[str] = []
    if not existing.strip():
        lines.append(f"# GitHub issues — daily log {date}")
        lines.append("")
        lines.append(f"Repo: `{repo}`")
        lines.append("")
    else:
        lines.append(existing.rstrip())
        lines.append("")

    lines.append("## Sweep")
    if window:
        lines.append(
            f"- Window: `{window.get('since')}` → anchor candidate `{window.get('anchor')}`"
            f" (first_run={window.get('first_run', False)})"
        )
    for key in (
        "closed",
        "pr_reconciled",
        "triaged",
        "duplicates",
        "stale_nudges",
        "weekly_digest",
        "index_changes",
        "notes",
    ):
        val = sections.get(key)
        if val is None:
            continue
        lines.append(f"### {key.replace('_', ' ').title()}")
        if isinstance(val, str):
            lines.append(val.rstrip())
        elif isinstance(val, list):
            for item in val:
                if isinstance(item, dict):
                    lines.append(f"- {json.dumps(item, sort_keys=True)}")
                else:
                    lines.append(f"- {item}")
        elif isinstance(val, dict):
            lines.append("```json")
            lines.append(json.dumps(val, indent=2, sort_keys=True))
            lines.append("```")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def daily_path(directory: Path, date: str) -> Path:
    """Return ``<directory>/YYYY-MM-DD.md``."""
    return directory / f"{date}.md"


def main(argv: list[str] | None = None) -> int:
    """CLI for index upsert/remove and daily append."""
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init-index")
    p_init.add_argument("--index", required=True)
    p_init.add_argument("--repo", default="sevn-bot/sevn")

    p_up = sub.add_parser("upsert")
    p_up.add_argument("--index", required=True)
    p_up.add_argument("--entry-json", required=True)

    p_rm = sub.add_parser("remove")
    p_rm.add_argument("--index", required=True)
    p_rm.add_argument("--number", type=int, required=True)

    p_day = sub.add_parser("append-daily")
    p_day.add_argument("--dir", required=True)
    p_day.add_argument("--date", required=True, help="YYYY-MM-DD")
    p_day.add_argument("--repo", default="sevn-bot/sevn")
    p_day.add_argument("--section-json", required=True)

    args = ap.parse_args(argv)

    if args.cmd == "init-index":
        path = Path(args.index)
        if not path.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(empty_index(args.repo), encoding="utf-8")
        print(path)
        return 0

    if args.cmd == "upsert":
        path = Path(args.index)
        text = path.read_text(encoding="utf-8") if path.is_file() else empty_index()
        with open(args.entry_json, encoding="utf-8") as fh:
            entry = json.load(fh)
        if not isinstance(entry, dict) or entry.get("number") is None:
            sys.exit("entry JSON must include number")
        new_text = upsert_index(text, entry)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8")
        print(path)
        return 0

    if args.cmd == "remove":
        path = Path(args.index)
        if not path.is_file():
            print(path)
            return 0
        new_text = remove_from_index(path.read_text(encoding="utf-8"), args.number)
        path.write_text(new_text, encoding="utf-8")
        print(path)
        return 0

    if args.cmd == "append-daily":
        directory = Path(args.dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = daily_path(directory, args.date)
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        with open(args.section_json, encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            sys.exit("section JSON must be an object")
        window = payload.get("window")
        sections = {k: v for k, v in payload.items() if k != "window"}
        new_text = append_daily_section(
            existing,
            date=args.date,
            repo=args.repo,
            window=window if isinstance(window, dict) else None,
            sections=sections,
        )
        path.write_text(new_text, encoding="utf-8")
        print(path)
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
