"""Tests for partial CI path routing and test discovery."""

from __future__ import annotations

from scripts.ci_lib import (
    REPO_ROOT,
    _module_dotted_name,
    _paired_test,
    _pattern_matches,
    build_python_gate_steps,
    discover_related_tests,
    match_path_rules,
)


def test_module_dotted_name_tripll() -> None:
    path = REPO_ROOT / "src/tripll/inject.py"
    assert _module_dotted_name(path) == "tripll.inject"


def test_paired_test_maps_flat_module() -> None:
    src = REPO_ROOT / "src/tripll/inject.py"
    paired = _paired_test(src)
    assert paired == REPO_ROOT / "tests/test_inject.py"


def test_paired_test_maps_nested_module() -> None:
    src = REPO_ROOT / "src/tripll/skw/validate.py"
    if not src.is_file():
        return
    paired = _paired_test(src)
    assert paired == REPO_ROOT / "tests/skw/test_validate.py"


def test_match_path_rules_about_site() -> None:
    targets = match_path_rules(["about-tripll/_sources/index.md"])
    assert targets == ["about-site-check"]


def test_match_path_rules_log_redact() -> None:
    targets = match_path_rules(["config/log-hide-keys.toml"])
    assert targets == ["log-redact-check"]


def test_match_path_rules_pullfrog() -> None:
    targets = match_path_rules([".github/workflows/pullfrog.yml"])
    assert targets == ["pullfrog-ref-check"]


def test_match_path_rules_changelog() -> None:
    targets = match_path_rules(["CHANGELOG.md"])
    assert targets == ["changelog-check"]


def test_pattern_matches_glob_prefix() -> None:
    assert _pattern_matches("about-tripll/_sources/foo.md", "about-tripll/_sources/**")


def test_discover_related_tests_includes_paired_file() -> None:
    src = REPO_ROOT / "src/tripll/inject.py"
    tests = discover_related_tests([src])
    assert REPO_ROOT / "tests/test_inject.py" in tests


def test_build_python_gate_steps_includes_typecheck() -> None:
    src = REPO_ROOT / "src/tripll/inject.py"
    if not src.is_file():
        return
    steps = build_python_gate_steps([src])
    labels = [label for label, _ in steps]
    assert "ruff check" in labels
    assert "mypy" in labels
    assert "pytest" in labels


def test_match_path_rules_dedupes_and_orders() -> None:
    targets = match_path_rules(
        [
            "CHANGELOG.md",
            "config/log-hide-keys.toml",
        ],
    )
    assert targets.index("log-redact-check") < targets.index("changelog-check")
