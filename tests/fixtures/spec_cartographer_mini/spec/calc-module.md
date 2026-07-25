---
id: spec-01-calc-module
kind: spec
title: Calculator Module
status: draft
owner: fixture
summary: Integer add and divide helpers in pkg/calc.py for spec-cartographer W11 e2e stub.
last_updated: '2026-07-25'
fingerprint: sha256:fixture-spec-cartographer-mini-calc
related: []
sources:
- pkg/calc.py
parent_prd: prd-01-fixture
depends_on: []
build_phase: null
interfaces:
- name: add
  file: pkg/calc.py
  symbol: add
- name: divide
  file: pkg/calc.py
  symbol: divide
---

## Purpose

The calculator module provides basic integer arithmetic for the fixture mini package.
Every claim cites `pkg/calc.py` as the single source module (`pkg/calc.py:6`, `pkg/calc.py:11`).

## Public Interface

- `add(a: int, b: int) -> int` — returns the sum (`pkg/calc.py:6`).
- `divide(a: int, b: int) -> float` — returns quotient; raises on zero divisor (`pkg/calc.py:11`).

## Data Model

Stateless pure functions; no persistent data structures.

## Internal Architecture

Single module `pkg/calc.py` with two exported functions and no sub-packages.

## Behavior

`add` always returns `a + b`. `divide` returns floating-point quotient when `b != 0`; otherwise
raises `ValueError` with message `division by zero` (`pkg/calc.py:13-15`).

## Failure Modes

- `divide(x, 0)` raises `ValueError` — callers must guard or catch.

## Test Strategy

Unit tests cover happy-path add/divide and divide-by-zero error (`tests/test_agent_roster.py`
validates this spec artifact scores ≥ 80).
