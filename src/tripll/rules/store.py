"""Rule and context-module storage under ``.tripll/`` (W2.2).

Exports:
    RuleStore — read/write/list rules and context modules from committed markdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — runtime store paths

from tripll.rules.model import (
    Rule,
    parse_rule_markdown,
    render_rule_markdown,
    validate_rule,
    validate_rule_id,
)
from tripll.rules.pack import ContextModule, parse_context_markdown, render_context_markdown

__all__ = ["RuleStore"]


@dataclass
class RuleStore:
    """Filesystem-backed rule store (graph replica lands in W3).

    Args:
        repo_root (Path): Repository root.
        rules_dir (Path | None): Rendered rule directory (default ``.tripll/rules``).
        context_dir (Path | None): Context module directory (default ``.tripll/context``).
    """

    repo_root: Path
    rules_dir: Path | None = None
    context_dir: Path | None = None

    def __post_init__(self) -> None:
        self.repo_root = self.repo_root.resolve()
        self._rules_dir = (self.rules_dir or self.repo_root / ".tripll" / "rules").resolve()
        self._context_dir = (self.context_dir or self.repo_root / ".tripll" / "context").resolve()

    @property
    def rules_path(self) -> Path:
        """Return the rules directory path."""
        return self._rules_dir

    @property
    def context_path(self) -> Path:
        """Return the context modules directory path."""
        return self._context_dir

    def ensure_dirs(self) -> None:
        """Create rules and context directories when absent."""
        self._rules_dir.mkdir(parents=True, exist_ok=True)
        self._context_dir.mkdir(parents=True, exist_ok=True)

    def list_rule_paths(self) -> list[Path]:
        """Return sorted rule markdown paths."""
        if not self._rules_dir.is_dir():
            return []
        return sorted(self._rules_dir.glob("*.md"))

    def read_rule(self, rule_id: str) -> Rule | None:
        """Load one rule by id, or ``None`` when missing."""
        validate_rule_id(rule_id)
        path = self._rules_dir / f"{rule_id}.md"
        if not path.is_file():
            return None
        return parse_rule_markdown(path.read_text(encoding="utf-8"))

    def write_rule(self, rule: Rule, *, force: bool = False, via_operator: bool = False) -> Path:
        """Write *rule* to ``<rules_dir>/<rule_id>.md``.

        Args:
            rule (Rule): Rule to persist.
            force (bool): Overwrite an existing file when True.
            via_operator (bool): When True, allow ``active``/``retired`` lifecycle writes (R27).

        Returns:
            Path: Written file path.

        Raises:
            FileExistsError: When the file exists and ``force`` is False.
            ValueError: When ``active``/``retired`` is written outside operator paths.
        """
        if rule.state in {"active", "retired"} and not via_operator:
            msg = (
                f"cannot write rule in state {rule.state!r} directly — "
                "use tripll rules promote/retire (R27)"
            )
            raise ValueError(msg)
        validate_rule(rule, repo_root=self.repo_root)
        self.ensure_dirs()
        path = self._rules_dir / f"{rule.rule_id}.md"
        if path.is_file() and not force:
            return path
        path.write_text(render_rule_markdown(rule), encoding="utf-8")
        return path

    def list_rules(self, *, state: str | None = None) -> list[Rule]:
        """Return all rules, optionally filtered by *state*."""
        rules: list[Rule] = []
        for path in self.list_rule_paths():
            rule = parse_rule_markdown(path.read_text(encoding="utf-8"))
            if state is None or rule.state == state:
                rules.append(rule)
        return rules

    def list_active(self) -> list[Rule]:
        """Return rules in ``active`` state."""
        return self.list_rules(state="active")

    def list_context_modules(self) -> list[ContextModule]:
        """Return parsed context modules from ``context_dir``."""
        if not self._context_dir.is_dir():
            return []
        modules: list[ContextModule] = []
        for path in sorted(self._context_dir.glob("*.md")):
            modules.append(
                parse_context_markdown(path.read_text(encoding="utf-8"), topic=path.stem)
            )
        return modules

    def write_context_module(
        self,
        module: ContextModule,
        *,
        force: bool = False,
    ) -> Path:
        """Write a context module markdown file.

        Args:
            module (ContextModule): Module to persist.
            force (bool): Overwrite when True.

        Returns:
            Path: Written file path.
        """
        self.ensure_dirs()
        path = self._context_dir / f"{module.topic}.md"
        if path.is_file() and not force:
            return path
        path.write_text(render_context_markdown(module), encoding="utf-8")
        return path

    def read_context_module(self, topic: str) -> ContextModule | None:
        """Load one context module by topic slug."""
        path = self._context_dir / f"{topic}.md"
        if not path.is_file():
            return None
        return parse_context_markdown(path.read_text(encoding="utf-8"), topic=topic)
