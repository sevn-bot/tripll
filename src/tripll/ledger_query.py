"""SQLite ledger read operations.

Exports:
    list_events — fetch events for a run, ordered by event_id (optionally paged).
    list_fired_exit_ids — distinct exit ids recorded via ``exit_fired`` events.
    latest_events_by_node — collapse events to one row per node_id (D2 hydration).
    get_run_cost — cumulative attempt cost (USD) for a run.
    get_run_cost_by_provider — per-backend cost rollup for a run.
    get_run — fetch one run row.
    get_wave — fetch one wave row.
    list_waves — all wave rows for a run.
    list_attempts — all attempt rows for a (run_id, node_id) pair.
"""

from __future__ import annotations

import json

from tripll.ledger_schema import AttemptRow, EventRow, LedgerConnection, RunRow, WaveRow


def list_events(
    lc: LedgerConnection,
    run_id: str,
    *,
    after_event_id: int = 0,
) -> list[EventRow]:
    """Return events for *run_id* ordered by ``event_id``.

    Reads are unlocked under WAL — callers do not need to hold
    ``_ledger_lock``.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        after_event_id (int): Return only events with ``event_id > after_event_id``
            (default 0 = return all).  Used by the SSE/poll layer to page from
            a ``Last-Event-ID`` cursor.

    Returns:
        list[EventRow]: Events ordered by ``event_id`` ascending.

    Examples:
        >>> from tripll.ledger_store import append_event, insert_run, insert_wave, open_ledger
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> _ = append_event(lc, run_id="r1", node_id="p:W1", phase="running")
        >>> _ = append_event(lc, run_id="r1", node_id="p:W1", phase="done", cost_usd=0.05)
        >>> evts = list_events(lc, "r1")
        >>> [e.phase for e in evts]
        ['running', 'done']
        >>> paged = list_events(lc, "r1", after_event_id=evts[0].event_id)
        >>> len(paged)
        1
        >>> paged[0].phase
        'done'
        >>> lc.close()
    """
    rows = lc.conn.execute(
        """SELECT event_id, run_id, node_id, ts, phase,
                  last_action, input_tokens, output_tokens, cost_usd, attempt_n, metadata
           FROM events
           WHERE run_id = ? AND event_id > ?
           ORDER BY event_id""",
        (run_id, after_event_id),
    ).fetchall()
    return [
        EventRow(
            event_id=int(r[0]),
            run_id=str(r[1]),
            node_id=str(r[2]),
            ts=str(r[3]),
            phase=str(r[4]),
            last_action=str(r[5]) if r[5] is not None else None,
            input_tokens=int(r[6]) if r[6] is not None else None,
            output_tokens=int(r[7]) if r[7] is not None else None,
            cost_usd=float(r[8]) if r[8] is not None else None,
            attempt_n=int(r[9]) if r[9] is not None else None,
            metadata=str(r[10]) if r[10] is not None else None,
        )
        for r in rows
    ]


def list_fired_exit_ids(lc: LedgerConnection, run_id: str) -> list[int]:
    """Return distinct exit ids recorded via ``exit_fired`` events.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.

    Returns:
        list[int]: Exit numbers in firing order (deduplicated).

    Examples:
        >>> from tripll.ledger_store import append_event, insert_run, open_ledger
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> _ = append_event(
        ...     lc,
        ...     run_id="r1",
        ...     node_id="__loop__",
        ...     phase="exit_fired",
        ...     metadata=json.dumps({"exit_id": 3, "name": "budget_cap"}),
        ... )
        >>> list_fired_exit_ids(lc, "r1")
        [3]
        >>> lc.close()
    """
    seen: set[int] = set()
    fired: list[int] = []
    for event in list_events(lc, run_id):
        if event.phase != "exit_fired" or not event.metadata:
            continue
        try:
            payload = json.loads(event.metadata)
            exit_id = int(payload.get("exit_id") or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if exit_id <= 0 or exit_id in seen:
            continue
        seen.add(exit_id)
        fired.append(exit_id)
    return fired


def latest_events_by_node(lc: LedgerConnection, run_id: str) -> dict[str, EventRow]:
    """Collapse append-only events to one row per ``node_id`` (D2).

    Uses the same algorithm as ``cli._status_watch``: the latest event sets
    ``phase`` and ``last_action``; cumulative ``input_tokens``, ``output_tokens``,
    and ``cost_usd`` carry forward from the last non-``None`` value per field.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.

    Returns:
        dict[str, EventRow]: Latest hydrated row keyed by ``node_id``.

    Examples:
        >>> from tripll.ledger_store import append_event, insert_run, insert_wave, open_ledger
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> _ = append_event(
        ...     lc, run_id="r1", node_id="p:W1", phase="running",
        ...     last_action="editing foo", input_tokens=10, output_tokens=5,
        ... )
        >>> _ = append_event(
        ...     lc, run_id="r1", node_id="p:W1", phase="running",
        ...     input_tokens=20, output_tokens=15, cost_usd=0.01,
        ... )
        >>> latest = latest_events_by_node(lc, "r1")
        >>> latest["p:W1"].phase
        'running'
        >>> latest["p:W1"].input_tokens
        20
        >>> latest["p:W1"].cost_usd
        0.01
        >>> lc.close()
    """
    collapsed: dict[str, EventRow] = {}
    for e in list_events(lc, run_id):
        prev = collapsed.get(e.node_id)
        collapsed[e.node_id] = EventRow(
            event_id=e.event_id,
            run_id=run_id,
            node_id=e.node_id,
            ts=e.ts,
            phase=e.phase,
            last_action=(
                e.last_action.strip()
                if e.last_action
                else (prev.last_action if prev is not None else None)
            ),
            input_tokens=(
                e.input_tokens
                if e.input_tokens is not None
                else (prev.input_tokens if prev else None)
            ),
            output_tokens=(
                e.output_tokens
                if e.output_tokens is not None
                else (prev.output_tokens if prev else None)
            ),
            cost_usd=e.cost_usd if e.cost_usd is not None else (prev.cost_usd if prev else None),
            attempt_n=(
                e.attempt_n if e.attempt_n is not None else (prev.attempt_n if prev else None)
            ),
            metadata=(e.metadata if e.metadata is not None else (prev.metadata if prev else None)),
        )
    return collapsed


def get_run_cost(lc: LedgerConnection, run_id: str) -> float:
    """Return cumulative provider cost (USD) derived from attempt rows.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run identifier.

    Returns:
        float: Total ``cost_usd`` for the run (0 when unset).

    Raises:
        KeyError: When *run_id* does not exist.
    """
    from tripll.ledger_store import _sum_attempt_costs

    exists = lc.conn.execute(
        "SELECT 1 FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if exists is None:
        raise KeyError(f"Run not found: {run_id!r}")
    return _sum_attempt_costs(lc, run_id)


def get_run_cost_by_provider(lc: LedgerConnection, run_id: str) -> dict[str, float]:
    """Return per-backend cost rollup for *run_id*.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run identifier.

    Returns:
        dict[str, float]: ``backend`` → summed ``cost_usd``.

    Raises:
        KeyError: When *run_id* does not exist.

    Examples:
        >>> from tripll.ledger_store import insert_run, open_ledger
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="s", source_mode="A", input_path="/x")
        >>> get_run_cost_by_provider(lc, "r1")
        {}
    """
    exists = lc.conn.execute(
        "SELECT 1 FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if exists is None:
        raise KeyError(f"Run not found: {run_id!r}")
    rows = lc.conn.execute(
        """SELECT backend, COALESCE(SUM(cost_usd), 0)
           FROM attempts WHERE run_id = ? GROUP BY backend""",
        (run_id,),
    ).fetchall()
    return {str(row[0]): float(row[1]) for row in rows if row[0]}


def get_run(lc: LedgerConnection, run_id: str) -> RunRow:
    """Fetch a single run row.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Run identifier.

    Returns:
        RunRow: Hydrated row.

    Raises:
        KeyError: If *run_id* does not exist.

    Examples:
        >>> from tripll.ledger_store import insert_run, open_ledger
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="s", source_mode="B", input_path="/x")
        >>> get_run(lc, "r1").slug
        's'
        >>> lc.close()
    """
    row = lc.conn.execute(
        "SELECT run_id, slug, source_mode, input_path, state, created_at, updated_at, graph_json, cost_usd "
        "FROM runs WHERE run_id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Run not found: {run_id!r}")
    return RunRow(
        run_id=str(row[0]),
        slug=str(row[1]),
        source_mode=str(row[2]),
        input_path=str(row[3]),
        state=str(row[4]),
        created_at=str(row[5]),
        updated_at=str(row[6]),
        graph_json=str(row[7]) if row[7] is not None else None,
        cost_usd=float(row[8] or 0.0),
    )


def get_wave(lc: LedgerConnection, run_id: str, node_id: str) -> WaveRow:
    """Fetch a single wave row.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Wave node identifier.

    Returns:
        WaveRow: Hydrated row.

    Raises:
        KeyError: If ``(run_id, node_id)`` does not exist.

    Examples:
        >>> from tripll.ledger_store import insert_run, insert_wave, open_ledger
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W0", run_id="r1", plan_id="p", wave_id="W0", lane="l")
        >>> get_wave(lc, "r1", "p:W0").wave_id
        'W0'
        >>> lc.close()
    """
    row = lc.conn.execute(
        """SELECT node_id, run_id, plan_id, wave_id, lane, state, attempt_count,
                  created_at, updated_at
           FROM waves WHERE run_id = ? AND node_id = ?""",
        (run_id, node_id),
    ).fetchone()
    if row is None:
        raise KeyError(f"Wave not found: run={run_id!r} node={node_id!r}")
    return WaveRow(
        node_id=str(row[0]),
        run_id=str(row[1]),
        plan_id=str(row[2]),
        wave_id=str(row[3]),
        lane=str(row[4]),
        state=str(row[5]),
        attempt_count=int(str(row[6])),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )


def list_waves(lc: LedgerConnection, run_id: str) -> list[WaveRow]:
    """Return all wave rows for *run_id*, ordered by ``created_at``.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.

    Returns:
        list[WaveRow]: All wave rows for this run.

    Examples:
        >>> from tripll.ledger_store import insert_run, insert_wave, open_ledger
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W0", run_id="r1", plan_id="p", wave_id="W0", lane="l")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> [w.wave_id for w in list_waves(lc, "r1")]
        ['W0', 'W1']
        >>> lc.close()
    """
    rows = lc.conn.execute(
        """SELECT node_id, run_id, plan_id, wave_id, lane, state, attempt_count,
                  created_at, updated_at
           FROM waves WHERE run_id = ? ORDER BY created_at""",
        (run_id,),
    ).fetchall()
    return [
        WaveRow(
            node_id=str(r[0]),
            run_id=str(r[1]),
            plan_id=str(r[2]),
            wave_id=str(r[3]),
            lane=str(r[4]),
            state=str(r[5]),
            attempt_count=int(str(r[6])),
            created_at=str(r[7]),
            updated_at=str(r[8]),
        )
        for r in rows
    ]


def list_attempts(lc: LedgerConnection, run_id: str, node_id: str) -> list[AttemptRow]:
    """Return all attempt rows for a ``(run_id, node_id)`` pair, ordered by ``attempt_n``.

    Args:
        lc (LedgerConnection): Open ledger connection.
        run_id (str): Parent run.
        node_id (str): Target wave node.

    Returns:
        list[AttemptRow]: All attempt rows for this wave.

    Examples:
        >>> from tripll.ledger_store import insert_attempt, insert_run, insert_wave, open_ledger
        >>> lc = open_ledger(":memory:")
        >>> insert_run(lc, run_id="r1", slug="t", source_mode="A", input_path="/tmp")
        >>> insert_wave(lc, node_id="p:W1", run_id="r1", plan_id="p", wave_id="W1", lane="l")
        >>> _ = insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=1, backend="claude_code")
        >>> _ = insert_attempt(lc, run_id="r1", node_id="p:W1", attempt_n=2, backend="claude_code")
        >>> len(list_attempts(lc, "r1", "p:W1"))
        2
        >>> lc.close()
    """
    rows = lc.conn.execute(
        """SELECT attempt_id, run_id, node_id, attempt_n, backend,
                  brief_path, log_path, started_at, ended_at, outcome, evidence,
                  cost_usd, input_tokens, output_tokens,
                  env_fingerprint_json, env_fingerprint_hash
           FROM attempts
           WHERE run_id = ? AND node_id = ?
           ORDER BY attempt_n""",
        (run_id, node_id),
    ).fetchall()
    return [
        AttemptRow(
            attempt_id=str(r[0]),
            run_id=str(r[1]),
            node_id=str(r[2]),
            attempt_n=int(str(r[3])),
            backend=str(r[4]),
            brief_path=str(r[5]) if r[5] is not None else None,
            log_path=str(r[6]) if r[6] is not None else None,
            started_at=str(r[7]),
            ended_at=str(r[8]) if r[8] is not None else None,
            outcome=str(r[9]) if r[9] is not None else None,
            evidence=str(r[10]) if r[10] is not None else None,
            cost_usd=float(r[11]) if r[11] is not None else None,
            input_tokens=int(r[12]) if r[12] is not None else None,
            output_tokens=int(r[13]) if r[13] is not None else None,
            env_fingerprint_json=str(r[14]) if r[14] is not None else None,
            env_fingerprint_hash=str(r[15]) if r[15] is not None else None,
        )
        for r in rows
    ]
