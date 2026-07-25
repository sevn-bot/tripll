#!/usr/bin/env python3
"""Human-in-the-loop reproduction loop template.

Port of the upstream ``hitl-loop.template.sh`` bash helper to stdlib Python
(kit is Python-first — locked decision D5). Copy this file, edit the steps
in ``run_steps()`` below, and run it. The agent runs the script; the user
follows prompts in their terminal.

Usage:
    python3 hitl_loop.py

Two helpers:
    step(instruction)              -> show instruction, wait for Enter
    capture(question) -> str       -> show question, read response, return it

At the end, captured values are printed as ``KEY=VALUE`` lines for the agent
to parse (stdout only — safe to pipe/capture).

**Provenance:** derived from
mattpocock/skills/engineering/diagnosing-bugs/scripts/hitl-loop.template.sh
(MIT), ported bash -> stdlib Python.
"""

from __future__ import annotations


def step(instruction: str) -> None:
    """Show an instruction to the human operator and wait for Enter.

    Args:
        instruction: What the human should do next.
    """
    print(f"\n>>> {instruction}")
    input("    [Enter when done] ")


def capture(question: str) -> str:
    """Show a question to the human operator and capture their answer.

    Args:
        question: What to ask the human.

    Returns:
        The raw string the human typed (leading/trailing whitespace
        stripped).
    """
    print(f"\n>>> {question}")
    answer = input("    > ")
    return answer.strip()


def run_steps() -> dict[str, str]:
    """Run the HITL script. Edit the body below for the bug at hand.

    Returns:
        Captured KEY -> value pairs, in the order they were collected.
    """
    captured: dict[str, str] = {}

    # --- edit below -----------------------------------------------------

    step("Open the app at http://localhost:3000 and sign in.")

    captured["ERRORED"] = capture("Click the 'Export' button. Did it throw an error? (y/n)")
    captured["ERROR_MSG"] = capture("Paste the error message (or 'none'):")

    # --- edit above -----------------------------------------------------

    return captured


def main() -> None:
    """Entry point: run the steps, then print captured values as KEY=VALUE."""
    captured = run_steps()
    print("\n--- Captured ---")
    for key, value in captured.items():
        print(f"{key}={value}")


if __name__ == "__main__":
    main()
