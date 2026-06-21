"""Tests for agent selection: ``test-author`` node dispatches to ``test-creator``.

Covers W1.3 of the test-creator-tests-first wave plan: agent selection routing
(``test-author`` → ``test-creator``; ``impl`` → ``wave-runner``) and
``OrchestratorConfig.agent_test`` + ``ParsedOrchestratorPrompt.agent_test`` parsing.

Coverage matrix (W1.6):
  Unit:        OrchestratorConfig.agent_test default, ParsedOrchestratorPrompt.agent_test.
  Integration: brief renders correct agent for test-author vs impl nodes.
  Edge cases:  Custom agent_test override, missing orchestrator config.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tripll.graph import OrchestratorConfig, WaveNode
from tripll.parse.orchestrator_prompt import ParsedOrchestratorPrompt

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# W1.3 — Unit: OrchestratorConfig.agent_test field
# ---------------------------------------------------------------------------


class TestOrchestratorConfigAgentTest:
    """OrchestratorConfig gains agent_test field (design-note §9.3)."""

    def test_default_agent_test_is_test_creator(self) -> None:
        cfg = OrchestratorConfig(enabled=True, prompt_path="p.md")
        assert cfg.agent_test == "test-creator"

    def test_custom_agent_test(self) -> None:
        cfg = OrchestratorConfig(enabled=True, prompt_path="p.md", agent_test="custom-test-agent")
        assert cfg.agent_test == "custom-test-agent"

    def test_agent_test_coexists_with_agent_wave(self) -> None:
        cfg = OrchestratorConfig(
            enabled=True,
            prompt_path="p.md",
            agent_wave="wave-runner",
            agent_test="test-creator",
        )
        assert cfg.agent_wave == "wave-runner"
        assert cfg.agent_test == "test-creator"


# ---------------------------------------------------------------------------
# W1.3 — Unit: ParsedOrchestratorPrompt.agent_test field
# ---------------------------------------------------------------------------


class TestParsedPromptAgentTest:
    """ParsedOrchestratorPrompt gains agent_test field (design-note §9.3)."""

    def test_default_agent_test_is_test_creator(self) -> None:
        pp = ParsedOrchestratorPrompt(prompt_path="p.md")
        assert pp.agent_test == "test-creator"

    def test_agent_test_mirrors_agent_wave_pattern(self) -> None:
        """agent_test follows the same pattern as agent_wave/agent_orchestrator."""
        pp = ParsedOrchestratorPrompt(prompt_path="p.md")
        assert hasattr(pp, "agent_wave")
        assert hasattr(pp, "agent_orchestrator")
        assert hasattr(pp, "agent_test")


# ---------------------------------------------------------------------------
# W1.3 — Integration: agent_test parsed from orchestrator prompt text
# ---------------------------------------------------------------------------


class TestAgentTestParsedFromPrompt:
    """parse_orchestrator_prompt extracts agent_test from prompt text."""

    def test_agent_test_parsed_from_prompt(self, tmp_path: Path) -> None:
        from tripll.parse.orchestrator_prompt import parse_orchestrator_prompt

        prompt_text = (
            "Feature branch: `feature/demo`\n\n"
            "```text\nW0 → W1 → W2 → Final\n```\n\n"
            "agent_test: my-custom-tester\n"
        )
        p = tmp_path / "demo-orchestrator-prompt.md"
        p.write_text(prompt_text)
        parsed = parse_orchestrator_prompt(p)
        assert parsed.agent_test == "my-custom-tester"

    def test_agent_test_defaults_when_not_in_prompt(self, tmp_path: Path) -> None:
        from tripll.parse.orchestrator_prompt import parse_orchestrator_prompt

        prompt_text = "Feature branch: `feature/demo`\n\n```text\nW0 → W1 → Final\n```\n"
        p = tmp_path / "demo-orchestrator-prompt.md"
        p.write_text(prompt_text)
        parsed = parse_orchestrator_prompt(p)
        assert parsed.agent_test == "test-creator"


# ---------------------------------------------------------------------------
# W1.3 — Integration: agent_test propagates through build_orchestrator_config
# ---------------------------------------------------------------------------


class TestAgentTestInConfig:
    """build_orchestrator_config propagates agent_test to OrchestratorConfig."""

    def test_agent_test_in_built_config(self, tmp_path: Path) -> None:
        from tripll.parse.orchestrator_prompt import build_orchestrator_config

        prompt_text = "Feature branch: `feature/demo`\n\n```text\nW0 → W1\n```\n"
        (tmp_path / "demo-orchestrator-prompt.md").write_text(prompt_text)
        cfg = build_orchestrator_config(tmp_path)
        assert cfg is not None
        assert cfg.agent_test == "test-creator"


# ---------------------------------------------------------------------------
# W1.3 — Integration: brief renders correct agent per role
# ---------------------------------------------------------------------------


class TestBriefAgentSelection:
    """render_json_brief selects agent based on node role."""

    def _make_orchestrator(self, **kwargs: object) -> OrchestratorConfig:
        defaults = {
            "enabled": True,
            "prompt_path": "p.md",
            "agent_wave": "wave-runner",
            "agent_test": "test-creator",
        }
        defaults.update(kwargs)
        return OrchestratorConfig(**defaults)  # type: ignore[arg-type]

    def test_impl_node_gets_wave_runner(self) -> None:
        from tripll.brief import render_json_brief

        node = WaveNode(
            "demo:W2",
            "demo",
            "x.md",
            "W2",
            "demo",
            owned_paths=["src/demo/"],
            role="impl",
        )
        orch = self._make_orchestrator()
        brief = render_json_brief(
            node,
            run_id="r",
            branch="b",
            worktree_path="w",
            orchestrator=orch,
        )
        assert brief.get("agent") == "wave-runner"

    def test_test_author_node_gets_test_creator(self) -> None:
        from tripll.brief import render_json_brief

        node = WaveNode(
            "demo:W1",
            "demo",
            "x.md",
            "W1",
            "demo",
            owned_paths=["src/demo/"],
            role="test-author",
        )
        orch = self._make_orchestrator()
        brief = render_json_brief(
            node,
            run_id="r",
            branch="b",
            worktree_path="w",
            orchestrator=orch,
        )
        assert brief.get("agent") == "test-creator"

    def test_custom_agent_test_used(self) -> None:
        from tripll.brief import render_json_brief

        node = WaveNode(
            "demo:W1",
            "demo",
            "x.md",
            "W1",
            "demo",
            owned_paths=["src/demo/"],
            role="test-author",
        )
        orch = self._make_orchestrator(agent_test="my-custom-tester")
        brief = render_json_brief(
            node,
            run_id="r",
            branch="b",
            worktree_path="w",
            orchestrator=orch,
        )
        assert brief.get("agent") == "my-custom-tester"


# ---------------------------------------------------------------------------
# W1.6 — Edge: no orchestrator config — agent key absent
# ---------------------------------------------------------------------------


class TestNoOrchestratorAgentKey:
    """Without orchestrator config, no agent key in the brief (current behavior)."""

    def test_no_orchestrator_no_agent_key(self) -> None:
        from tripll.brief import render_json_brief

        node = WaveNode(
            "demo:W2",
            "demo",
            "x.md",
            "W2",
            "demo",
            owned_paths=["src/demo/"],
        )
        brief = render_json_brief(node, run_id="r", branch="b", worktree_path="w")
        assert "agent" not in brief
