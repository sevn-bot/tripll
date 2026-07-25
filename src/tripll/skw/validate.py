"""spec-kit-wave validate — strict wave-file v2 validator (stdlib only).

Exports:
    KNOWN_AGENTS — built-in pipeline agent ids.
    VALID_EFFORTS — allowed effort values.
    VALID_ROLES — allowed role values.
    extract_toml_block — parse the first fenced toml block from markdown.
    find_bad_path_refs — collect forbidden in-repo path patterns.
    load_skw_config — read ``skw.toml`` merged with defaults.
    validate_wave_file — return errors and warnings for one wave-file.
    main — CLI entry (``--json`` mode for the driver).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import Any

from tripll.skw.markdown_sections import section_bullets, wave_heading_map

KNOWN_AGENTS = frozenset(
    {
        "wave-runner",
        "test-creator",
        "reviewer",
        "post-review-wave-generator",
        "orchestrator",
        "wave-generator",
    }
)
VALID_EFFORTS = frozenset({"S", "M", "L"})
VALID_ROLES = frozenset({"impl", "test-author"})
VALID_THINKING = frozenset({"low", "medium", "high", "xhigh", "max"})

_TOML_FENCE_RE = re.compile(r"```toml\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_MD_LINK_RE = re.compile(r"\]\(([^)]+)\)")
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")


def extract_toml_block(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Extract and parse the first fenced ``toml`` block from *text*.

    Args:
        text (str): Full wave-file markdown body.

    Returns:
        tuple[dict[str, Any] | None, str | None]: ``(parsed, error)`` — error set when
        the block is missing or TOML is invalid.

    Examples:
        >>> data, err = extract_toml_block("```toml\\nwaveorch_format = 2\\n```")
        >>> err is None and data["waveorch_format"] == 2
        True
    """
    match = _TOML_FENCE_RE.search(text)
    if not match:
        return None, "missing first ```toml fenced block"
    raw = match.group(1)
    try:
        return tomllib.loads(raw), None
    except tomllib.TOMLDecodeError as exc:
        return None, f"invalid TOML in fenced block: {exc}"


def _split_anchor(ref: str) -> tuple[str, str]:
    if "#" in ref:
        path, anchor = ref.split("#", 1)
        return path, f"#{anchor}"
    return ref, ""


def _is_external_url(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith(("http://", "https://", "mailto:"))


def _is_anchor_token(path: str) -> bool:
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


def _parent_dir_prefix() -> str:
    return chr(46) + chr(46) + chr(47)


def _forbidden_path_reason(path_part: str) -> str | None:
    parent = _parent_dir_prefix()
    if path_part.startswith(parent):
        return "forbidden parent ref: path starts with parent-directory prefix"
    if path_part.startswith("./"):
        return "forbidden path: path starts with ./"
    if path_part.startswith("/"):
        return "forbidden path: path starts with /"
    embedded = chr(47) + parent
    if embedded in path_part or path_part.startswith(".."):
        return "forbidden parent ref: path contains parent-directory segment"
    return None


def find_bad_path_refs(text: str) -> list[str]:
    """Return human-readable errors for forbidden in-repo path patterns in *text*.

    Args:
        text (str): Markdown body to scan.

    Returns:
        list[str]: Error strings (empty when all refs are clean).

    Examples:
        >>> bad = "[x](" + _parent_dir_prefix() + "foo.md)"
        >>> find_bad_path_refs(bad)[0].startswith("forbidden parent ref")
        True
    """
    errors: list[str] = []
    seen: set[str] = set()
    spans: list[tuple[str, str]] = []
    for match in _MD_LINK_RE.finditer(text):
        spans.append(("link target", match.group(1)))
    for match in _BACKTICK_RE.finditer(text):
        token = match.group(1)
        if _looks_like_path(token):
            spans.append(("backtick path", token))
    for kind, ref in spans:
        raw = ref.strip()
        if raw in seen:
            continue
        path_part, _ = _split_anchor(raw)
        if not path_part or _is_external_url(path_part) or _is_anchor_token(path_part):
            continue
        reason = _forbidden_path_reason(path_part)
        if reason:
            seen.add(raw)
            errors.append(f"{reason} in {kind} {raw}")
    return errors


_DEFAULT_SKW: dict[str, Any] = {
    "base": "origin/main",
    "max_turns": 3,
    "agent": {
        "bin": "cursor-agent",
        "model": "auto",
        "max_tokens": None,
        "temperature": None,
        "thinking": "",
        "extra_args": [],
        "models": {},
        "perms": "--force",
        "plugin_dir": "",
    },
    "verify": {"make_only": True},
    "git": {"commit_per_wave": True, "push_per_wave": True, "remote": "origin"},
    "tracing": {"enabled": False, "token": ""},
    "logging": {"enabled": False},
}


def load_skw_config(kit_root: Path, *, strict: bool = False) -> dict[str, Any]:
    """Load ``skw.toml`` merged with built-in defaults.

    Args:
        kit_root (Path): Kit root directory containing ``skw.toml``.
        strict (bool): When ``True``, raise on TOML decode errors instead of returning
            defaults (used by ``validate_wave_file``).

    Returns:
        dict[str, Any]: Config with ``base``, ``max_turns``, ``agent``, ``verify``, ``git``,
            ``tracing``, ``logging`` keys.

    Raises:
        ValueError: When ``strict`` is ``True`` and ``skw.toml`` is invalid TOML.

    Examples:
        >>> cfg = load_skw_config(Path("."))
        >>> "verify" in cfg and "agent" in cfg and "git" in cfg
        True
    """
    cfg: dict[str, Any] = {
        "base": _DEFAULT_SKW["base"],
        "max_turns": _DEFAULT_SKW["max_turns"],
        "agent": dict(_DEFAULT_SKW["agent"]),
        "verify": dict(_DEFAULT_SKW["verify"]),
        "git": dict(_DEFAULT_SKW["git"]),
        "tracing": dict(_DEFAULT_SKW["tracing"]),
        "logging": dict(_DEFAULT_SKW["logging"]),
    }
    skw_path = kit_root / "skw.toml"
    if not skw_path.is_file():
        return cfg
    try:
        data = tomllib.loads(skw_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        if strict:
            msg = f"invalid skw.toml: {exc}"
            raise ValueError(msg) from exc
        return cfg
    if isinstance(data.get("base"), str) and data["base"].strip():
        cfg["base"] = data["base"].strip()
    max_turns = data.get("max_turns")
    if isinstance(max_turns, int) and max_turns >= 1:
        cfg["max_turns"] = max_turns
    agent = data.get("agent", {})
    if isinstance(agent, dict):
        for key in ("bin", "model", "perms", "plugin_dir", "thinking"):
            val = agent.get(key)
            if isinstance(val, str):
                cfg["agent"][key] = val
        for key in ("max_tokens", "max_token_out"):
            val = agent.get(key)
            if isinstance(val, int):
                cfg["agent"]["max_tokens"] = val
                break
        temp = agent.get("temperature")
        if isinstance(temp, (int, float)):
            cfg["agent"]["temperature"] = float(temp)
        extra = agent.get("extra_args")
        if isinstance(extra, list):
            cfg["agent"]["extra_args"] = [str(v) for v in extra if str(v).strip()]
        models = agent.get("models")
        if isinstance(models, dict):
            cfg["agent"]["models"] = {
                str(agent_id): table
                for agent_id, table in models.items()
                if isinstance(agent_id, str) and isinstance(table, dict)
            }
    verify = data.get("verify", {})
    if isinstance(verify, dict) and "make_only" in verify:
        cfg["verify"]["make_only"] = bool(verify["make_only"])
    git = data.get("git", {})
    if isinstance(git, dict):
        for key in ("commit_per_wave", "push_per_wave"):
            if key in git:
                cfg["git"][key] = bool(git[key])
        remote = git.get("remote")
        if isinstance(remote, str) and remote.strip():
            cfg["git"]["remote"] = remote.strip()
    tracing = data.get("tracing", {})
    if isinstance(tracing, dict):
        if "enabled" in tracing:
            cfg["tracing"]["enabled"] = bool(tracing["enabled"])
        token = tracing.get("token")
        if isinstance(token, str):
            cfg["tracing"]["token"] = token.strip()
    logging_cfg = data.get("logging", {})
    if isinstance(logging_cfg, dict) and "enabled" in logging_cfg:
        cfg["logging"]["enabled"] = bool(logging_cfg["enabled"])
    return cfg


def _check_model_table(prefix: str, table: Any, errors: list[str], *, warnings: list[str]) -> None:
    if not isinstance(table, dict):
        errors.append(f"{prefix} must be a table")
        return
    allowed = {"model", "max_tokens", "max_token_out", "temperature", "thinking", "extra_args"}
    for key, val in table.items():
        if key not in allowed:
            warnings.append(f"{prefix}: unknown key {key!r} (ignored by validator)")
            continue
        if key == "model" and not (isinstance(val, str) and val.strip()):
            errors.append(f"{prefix}.model must be a non-empty string")
        elif key in ("max_tokens", "max_token_out") and not isinstance(val, int):
            errors.append(f"{prefix}.{key} must be an integer")
        elif key == "temperature" and not isinstance(val, (int, float)):
            errors.append(f"{prefix}.temperature must be a number")
        elif key == "thinking" and (
            not isinstance(val, str) or val.strip().lower() not in VALID_THINKING
        ):
            errors.append(f"{prefix}.thinking must be one of {sorted(VALID_THINKING)}")
        elif key == "extra_args" and not isinstance(val, list):
            errors.append(f"{prefix}.extra_args must be a list of strings")


def _check_pipeline_models(
    data: dict[str, Any],
    display: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    pipeline = data.get("pipeline")
    if not isinstance(pipeline, dict):
        return
    global_model = pipeline.get("model")
    if global_model is not None:
        _check_model_table(f"{display}: [pipeline.model]", global_model, errors, warnings=warnings)
    models = pipeline.get("models")
    if isinstance(models, dict):
        for agent_id, table in models.items():
            if not isinstance(agent_id, str) or not agent_id.strip():
                errors.append(f"{display}: pipeline.models keys must be non-empty strings")
                continue
            if agent_id not in KNOWN_AGENTS:
                warnings.append(f"{display}: pipeline.models.{agent_id} is not a known agent id")
            _check_model_table(
                f"{display}: [pipeline.models.{agent_id}]",
                table,
                errors,
                warnings=warnings,
            )
    for stage in ("run", "review", "generate"):
        stage_data = pipeline.get(stage)
        if isinstance(stage_data, dict) and "model" in stage_data:
            _check_model_table(
                f"{display}: [pipeline.{stage}.model]",
                stage_data.get("model"),
                errors,
                warnings=warnings,
            )


def _check_pipeline_stage(
    data: dict[str, Any],
    kit_root: Path,
    stage: str,
    errors: list[str],
) -> None:
    pipeline = data.get("pipeline")
    if not isinstance(pipeline, dict):
        return
    stage_data = pipeline.get(stage)
    if not isinstance(stage_data, dict):
        errors.append(f"pipeline.{stage} must be a table")
        return
    agent = stage_data.get("agent")
    prompt = stage_data.get("prompt")
    if not isinstance(agent, str) or not agent.strip():
        errors.append(f"pipeline.{stage}.agent must be a non-empty string")
    elif agent not in KNOWN_AGENTS:
        errors.append(
            f"pipeline.{stage}.agent '{agent}' is unknown (expected one of {sorted(KNOWN_AGENTS)})"
        )
    if not isinstance(prompt, str) or not prompt.strip():
        errors.append(f"pipeline.{stage}.prompt must be a non-empty string")
    else:
        prompt_path = kit_root / prompt
        if not prompt_path.is_file():
            errors.append(f"pipeline.{stage}.prompt file not found: {prompt}")


def _transitive_deps(wave_ids: dict[str, list[str]], wid: str) -> set[str]:
    """Return all wave ids reachable following depends_on from *wid* (transitive)."""
    seen: set[str] = set()
    stack = list(wave_ids.get(wid, []))
    while stack:
        dep = stack.pop()
        if dep in seen:
            continue
        seen.add(dep)
        stack.extend(wave_ids.get(dep, []))
    return seen


def _prerequisites_of(wave_ids: dict[str, list[str]], target: str) -> set[str]:
    """Return wave ids that must finish before *target* (transitive depends_on from target)."""
    return _transitive_deps(wave_ids, target)


def _check_cycles(wave_ids: dict[str, list[str]], errors: list[str]) -> None:
    white, grey, black = 0, 1, 2
    color: dict[str, int] = {wid: white for wid in wave_ids}
    cycle_reported = False

    def visit(wid: str, stack: list[str]) -> None:
        nonlocal cycle_reported
        color[wid] = grey
        stack.append(wid)
        for dep in wave_ids.get(wid, []):
            if dep not in wave_ids:
                continue
            if color[dep] == grey:
                if not cycle_reported:
                    cycle = [*stack[stack.index(dep) :], dep]
                    errors.append("cycle detected: " + " → ".join(cycle))
                    cycle_reported = True
            elif color[dep] == white:
                visit(dep, stack)
        stack.pop()
        color[wid] = black

    for wid in wave_ids:
        if color[wid] == white:
            visit(wid, [])


def validate_wave_file(
    wave_path: Path,
    kit_root: Path,
    *,
    make_only: bool | None = None,
) -> tuple[list[str], list[str]]:
    """Validate one wave-file against the v2 contract.

    Args:
        wave_path (Path): Path to the wave markdown file.
        kit_root (Path): Kit root directory (parent of ``scripts/``).
        make_only (bool | None): When set, overrides ``skw.toml`` verify policy.

    Returns:
        tuple[list[str], list[str]]: ``(errors, warnings)``.

    Examples:
        >>> from pathlib import Path
        >>> import tempfile
        >>> with tempfile.TemporaryDirectory() as d:
        ...     root = Path(d)
        ...     (root / "prompts").mkdir()
        ...     for name in ("wave-runner", "reviewer", "post-review-wave-generator"):
        ...         (root / "prompts" / f"{name}.md").write_text("ok")
        ...     wf = root / "wave.md"
        ...     wf.write_text(
        ...         '```toml\\nwaveorch_format = 2\\ntitle = "t"\\nslug = "s"\\n'
        ...         'base = "main"\\nbranch = "feat"\\n'
        ...         '[pipeline]\\nmax_turns = 1\\n'
        ...         '[pipeline.run]\\nagent = "wave-runner"\\nprompt = "prompts/wave-runner.md"\\n'
        ...         '[pipeline.review]\\nagent = "reviewer"\\nprompt = "prompts/reviewer.md"\\n'
        ...         '[pipeline.generate]\\nagent = "post-review-wave-generator"\\n'
        ...         'prompt = "prompts/post-review-wave-generator.md"\\n'
        ...         '[[waves]]\\nid = "W0"\\ntitle = "w"\\ndepends_on = []\\nverify = ["make lint"]\\n```\\n'
        ...         '## Wave W0 — w\\n- [ ] task\\n'
        ...     )
        ...     errs, warns = validate_wave_file(wf, root)
        ...     errs == []
        True
    """
    errors: list[str] = []
    warnings: list[str] = []
    display = wave_path.name

    if not wave_path.is_file():
        return [f"{display}: file not found"], warnings

    text = wave_path.read_text(encoding="utf-8")
    errors.extend([f"{display}: {msg}" for msg in find_bad_path_refs(text)])

    data, toml_err = extract_toml_block(text)
    if toml_err:
        errors.append(f"{display}: {toml_err}")
        return errors, warnings

    if data is None:
        errors.append(f"{display}: empty TOML block")
        return errors, warnings

    fmt = data.get("waveorch_format")
    if fmt not in (2, 3):
        errors.append(f"{display}: waveorch_format must be 2 or 3 (got {fmt!r})")
        return errors, warnings

    plan_v3 = data
    if fmt == 2:
        from tripll.plan.compat_v1_v2 import _v2_to_v3

        plan_v3 = _v2_to_v3(data)
        warnings.append(f"{display}: waveorch_format=2 is deprecated; validating as v3")

    try:
        from tripll.plan.shape_checks import compile_plan

        compile_plan(plan_v3)
    except ValueError as exc:
        errors.append(f"{display}: {exc}")

    for field in ("title", "slug", "base", "branch"):
        value = data.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{display}: {field} must be a non-empty string")

    pipeline = data.get("pipeline")
    if not isinstance(pipeline, dict):
        errors.append(f"{display}: [pipeline] must be a table")
        pipeline = {}

    max_turns = pipeline.get("max_turns")
    if not isinstance(max_turns, int) or max_turns < 1:
        errors.append(f"{display}: pipeline.max_turns must be an integer ≥ 1")

    for stage in ("run", "review", "generate"):
        _check_pipeline_stage(data, kit_root, stage, errors)

    _check_pipeline_models(data, display, errors, warnings)

    waves = data.get("waves")
    if not isinstance(waves, list) or not waves:
        errors.append(f"{display}: [[waves]] must contain at least one wave row")
        return errors, warnings

    def _depends_on_ids(wave: dict[str, Any]) -> list[str]:
        deps = wave.get("depends_on", [])
        if deps is None:
            return []
        if not isinstance(deps, list):
            return []
        ids: list[str] = []
        for dep in deps:
            if isinstance(dep, str):
                ids.append(dep)
            elif isinstance(dep, dict):
                parent = dep.get("wave")
                if isinstance(parent, str) and parent.strip():
                    ids.append(parent)
        return ids

    wave_ids: dict[str, list[str]] = {}
    wave_roles: dict[str, str] = {}
    seen_ids: set[str] = set()

    for idx, wave in enumerate(waves):
        prefix = f"{display}: waves[{idx}]"
        if not isinstance(wave, dict):
            errors.append(f"{prefix} must be a table")
            continue
        wid = wave.get("id")
        if not isinstance(wid, str) or not wid.strip():
            errors.append(f"{prefix}.id must be a non-empty string")
            continue
        if wid in seen_ids:
            errors.append(f"{prefix}.id duplicate wave id '{wid}'")
        seen_ids.add(wid)
        title = wave.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"{prefix}.title must be a non-empty string")
        deps = wave.get("depends_on", [])
        if deps is None:
            deps = []
        if not isinstance(deps, list):
            errors.append(f"{prefix}.depends_on must be a list")
            deps = []
        dep_ids = _depends_on_ids(wave)
        wave_ids[wid] = dep_ids

        review_gate = wave.get("review_gate")
        if review_gate is not None and not isinstance(review_gate, bool):
            errors.append(f"{prefix}.review_gate must be a boolean")

        effort = wave.get("effort", "M")
        if not isinstance(effort, str):
            errors.append(f"{prefix}.effort must be a string")
        else:
            effort_key = effort.strip().upper()
            if effort_key not in VALID_EFFORTS:
                errors.append(
                    f"{prefix}.effort '{effort}' invalid (expected one of {sorted(VALID_EFFORTS)})"
                )

        role = wave.get("role", "impl")
        if not isinstance(role, str) or role not in VALID_ROLES:
            errors.append(f"{prefix}.role '{role}' invalid (expected one of {sorted(VALID_ROLES)})")
        else:
            wave_roles[wid] = role

        verify = wave.get("verify", [])
        if verify is None:
            verify = []
        if not isinstance(verify, list):
            errors.append(f"{prefix}.verify must be a list")
        else:
            cfg = load_skw_config(kit_root, strict=True)
            policy_make_only = make_only if make_only is not None else cfg["verify"]["make_only"]
            for entry in verify:
                if not isinstance(entry, str) or not entry.strip():
                    errors.append(f"{prefix}.verify entries must be non-empty strings")
                    continue
                if policy_make_only and not entry.startswith("make "):
                    errors.append(f"{prefix}.verify entry must start with 'make ': {entry!r}")
                elif not policy_make_only and not entry.startswith("make "):
                    warnings.append(f"{display}: verify entry without 'make ' prefix: {entry!r}")

    for wid, deps in wave_ids.items():
        for dep in deps:
            if dep not in wave_ids:
                errors.append(f"{display}: wave {wid} depends on unknown '{dep}'")

    cycle_errors: list[str] = []
    _check_cycles(wave_ids, cycle_errors)
    errors.extend([f"{display}: {e}" for e in cycle_errors])

    all_deps: set[str] = set()
    for deps in wave_ids.values():
        all_deps.update(deps)
    terminals = [wid for wid in wave_ids if wid not in all_deps]
    if wave_ids and not terminals:
        errors.append(f"{display}: graph has no terminal wave (every id is a dependency)")

    headings = wave_heading_map(text)

    for wid in wave_ids:
        if wid not in headings:
            errors.append(f"{display}: missing body heading for wave id '{wid}'")
        else:
            bullets = section_bullets(text, headings[wid])
            if not bullets:
                errors.append(f"{display}: wave section '{wid}' has no task bullets")

    for hid in headings:
        if hid not in wave_ids:
            errors.append(f"{display}: orphan heading for wave id '{hid}' (not in TOML graph)")

    test_author_ids = [wid for wid, role in wave_roles.items() if role == "test-author"]
    if len(test_author_ids) > 1:
        errors.append(
            f"{display}: at most one test-author wave allowed "
            f"(found {len(test_author_ids)}: {', '.join(test_author_ids)})"
        )
    elif len(test_author_ids) == 1:
        test_author_id = test_author_ids[0]
        prereqs = _prerequisites_of(wave_ids, test_author_id)
        for wid, role in wave_roles.items():
            if role != "impl":
                continue
            if wid in prereqs:
                continue
            deps = _transitive_deps(wave_ids, wid)
            if test_author_id not in deps:
                errors.append(
                    f"{display}: impl wave '{wid}' must depend on test-author wave "
                    f"'{test_author_id}' (directly or transitively via depends_on)"
                )

    return errors, warnings


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv (list[str] | None): Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        int: Exit code (0 = valid, 1 = invalid).

    Examples:
        >>> main(["--help"])  # doctest: +SKIP
        0
    """
    parser = argparse.ArgumentParser(description="Validate a spec-kit-wave wave-file (v2).")
    parser.add_argument("wave_file", type=Path, help="Path to the wave markdown file")
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=None,
        help="Kit root directory (default: parent of scripts/)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON result on stdout",
    )
    parser.add_argument(
        "--make-only",
        action="store_true",
        help="Force verify.make_only=true for this run",
    )
    parser.add_argument(
        "--no-make-only",
        action="store_true",
        help="Force verify.make_only=false for this run",
    )
    args = parser.parse_args(argv)

    kit_root = args.kit_root
    if kit_root is None:
        kit_root = Path(__file__).resolve().parent
    kit_root = kit_root.resolve()

    make_only: bool | None = None
    if args.make_only:
        make_only = True
    if args.no_make_only:
        make_only = False

    errors, warnings = validate_wave_file(
        args.wave_file.resolve(),
        kit_root,
        make_only=make_only,
    )
    ok = not errors

    if args.json:
        payload = {"ok": ok, "errors": errors, "warnings": warnings}
        print(json.dumps(payload, indent=2))
    else:
        for msg in errors:
            print(msg, file=sys.stderr)
        for msg in warnings:
            print(f"warning: {msg}", file=sys.stderr)
        if ok:
            print(f"ok: {args.wave_file}")
        else:
            print(f"invalid: {len(errors)} error(s)", file=sys.stderr)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
