"""tripll.profiles — persistent agent-profile store (W4).

Agent profiles are created once and reused across many runs.  Each profile
records which backend, model, agent definition, skills, and workspace-scope
hints to use.  A run references a ``profile_id``; waves inherit it.

Profiles are stored in a small dedicated SQLite database at the runs root
(``<runs_root>/control-plane.db``) so they are **global** across runs — not
per-run.  The schema is applied idempotently; seeding default profiles is
also idempotent.

Exports:
    ProfileRow — hydrated ``profiles`` row.
    ProfileStore — open/manage the control-plane database.
    open_profile_store — open (and migrate) the profile store at *path*.
    seed_default_profiles — idempotently insert one profile per available backend.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003

from loguru import logger

from tripll.adapters.claude_code import DEFAULT_MODEL

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_DDL = f"""
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS profiles (
    profile_id  TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    backend     TEXT NOT NULL,
    model       TEXT NOT NULL DEFAULT '{DEFAULT_MODEL}',
    agent       TEXT NOT NULL DEFAULT 'wave-plan-executor',
    skills      TEXT NOT NULL DEFAULT '[]',
    scope       TEXT NOT NULL DEFAULT '{{}}',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""
#: Default sub-agent definition name.
DEFAULT_AGENT = "wave-plan-executor"
#: Orchestrator-mode wave dispatch agent (D9).
ORCHESTRATOR_WAVE_AGENT = "wave-runner"


# ---------------------------------------------------------------------------
# Row dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProfileRow:
    """Hydrated ``profiles`` row.

    Args:
        profile_id (str): Stable slug primary key (e.g. ``claude-wave-executor``).
        name (str): Human-readable display name.
        backend (str): Backend identifier — ``claude_code`` | ``cursor_local`` |
            ``cursor_cloud``.
        model (str): Default model string (e.g. ``claude-sonnet-5``).
        agent (str): Local agent definition name (default ``wave-plan-executor``).
        skills (list[str]): Optional skill/tool allowlist (JSON-decoded from store).
        scope (dict[str, object]): Default workspace-scope hints (JSON-decoded).
        created_at (str): ISO-8601 UTC creation timestamp.
        updated_at (str): ISO-8601 UTC last-update timestamp.
    """

    profile_id: str
    name: str
    backend: str
    model: str
    agent: str
    skills: list[str]
    scope: dict[str, object]
    created_at: str
    updated_at: str


# ---------------------------------------------------------------------------
# Store wrapper
# ---------------------------------------------------------------------------


class ProfileStore:
    """Wrapper around the control-plane SQLite connection.

    Prefer :func:`open_profile_store` to construct.

    Args:
        conn (sqlite3.Connection): Already-open connection with schema applied.

    Examples:
        >>> import tempfile
        >>> from pathlib import Path
        >>> with tempfile.NamedTemporaryFile(suffix=".db") as f:
        ...     store = open_profile_store(Path(f.name))
        ...     store.conn.execute("SELECT count(*) FROM profiles").fetchone()
        (0,)
        ...     store.close()
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def close(self) -> None:
        """Close the underlying database connection."""
        self.conn.close()

    def __enter__(self) -> ProfileStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Open / migrate
# ---------------------------------------------------------------------------


def open_profile_store(path: Path | str) -> ProfileStore:
    """Open (and migrate) the control-plane profile store at *path*.

    Creates the file if it does not exist; applies DDL idempotently.

    Args:
        path (Path | str): Filesystem path to the ``control-plane.db`` file.
            Pass ``':memory:'`` for an in-memory store (tests).

    Returns:
        ProfileStore: Open store with schema applied.

    Examples:
        >>> store = open_profile_store(":memory:")
        >>> store.conn.execute("SELECT count(*) FROM profiles").fetchone()
        (0,)
        >>> store.close()
    """
    conn = sqlite3.connect(str(path))
    conn.executescript(_DDL)
    conn.commit()
    logger.debug("profiles: opened store at {}", path)
    return ProfileStore(conn)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _row_to_profile(row: tuple[object, ...]) -> ProfileRow:
    skills_raw = row[5] if row[5] is not None else "[]"
    scope_raw = row[6] if row[6] is not None else "{}"
    return ProfileRow(
        profile_id=str(row[0]),
        name=str(row[1]),
        backend=str(row[2]),
        model=str(row[3]),
        agent=str(row[4]),
        skills=json.loads(str(skills_raw)),
        scope=json.loads(str(scope_raw)),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------


def upsert_profile(
    store: ProfileStore,
    *,
    profile_id: str,
    name: str,
    backend: str,
    model: str = DEFAULT_MODEL,
    agent: str = DEFAULT_AGENT,
    skills: list[str] | None = None,
    scope: dict[str, object] | None = None,
) -> ProfileRow:
    """Insert or update a profile row and return it.

    If a profile with *profile_id* already exists it is updated; otherwise a
    new row is created.  The ``created_at`` timestamp is preserved on update.

    Args:
        store (ProfileStore): Open profile store.
        profile_id (str): Stable slug primary key.
        name (str): Human-readable display name.
        backend (str): Backend identifier.
        model (str): Default model string (default :data:`DEFAULT_MODEL`).
        agent (str): Local agent definition name (default :data:`DEFAULT_AGENT`).
        skills (list[str] | None): Skill/tool allowlist; defaults to ``[]``.
        scope (dict[str, object] | None): Workspace-scope hints; defaults to ``{}``.

    Returns:
        ProfileRow: The upserted profile row.

    Examples:
        >>> store = open_profile_store(":memory:")
        >>> p = upsert_profile(store, profile_id="x", name="X", backend="claude_code")
        >>> p.profile_id
        'x'
        >>> p.model
        'claude-sonnet-5'
        >>> store.close()
    """
    now = _now_iso()
    skills_json = json.dumps(skills or [])
    scope_json = json.dumps(scope or {})

    existing = store.conn.execute(
        "SELECT created_at FROM profiles WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    created_at = str(existing[0]) if existing else now

    store.conn.execute(
        """INSERT INTO profiles
               (profile_id, name, backend, model, agent, skills, scope, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(profile_id) DO UPDATE SET
               name = excluded.name,
               backend = excluded.backend,
               model = excluded.model,
               agent = excluded.agent,
               skills = excluded.skills,
               scope = excluded.scope,
               updated_at = excluded.updated_at""",
        (profile_id, name, backend, model, agent, skills_json, scope_json, created_at, now),
    )
    store.conn.commit()
    logger.debug("profiles: upserted profile {}", profile_id)
    return get_profile(store, profile_id)


def get_profile(store: ProfileStore, profile_id: str) -> ProfileRow:
    """Fetch a single profile row by *profile_id*.

    Args:
        store (ProfileStore): Open profile store.
        profile_id (str): Profile primary key.

    Returns:
        ProfileRow: Hydrated row.

    Raises:
        KeyError: If *profile_id* does not exist.

    Examples:
        >>> store = open_profile_store(":memory:")
        >>> _ = upsert_profile(store, profile_id="p1", name="P1", backend="claude_code")
        >>> get_profile(store, "p1").name
        'P1'
        >>> store.close()
    """
    row = store.conn.execute(
        """SELECT profile_id, name, backend, model, agent, skills, scope, created_at, updated_at
           FROM profiles WHERE profile_id = ?""",
        (profile_id,),
    ).fetchone()
    if row is None:
        raise KeyError(f"Profile not found: {profile_id!r}")
    return _row_to_profile(row)


def list_profiles(store: ProfileStore) -> list[ProfileRow]:
    """Return all profiles ordered by ``created_at``.

    Args:
        store (ProfileStore): Open profile store.

    Returns:
        list[ProfileRow]: All profiles in the store.

    Examples:
        >>> store = open_profile_store(":memory:")
        >>> _ = upsert_profile(store, profile_id="a", name="A", backend="claude_code")
        >>> _ = upsert_profile(store, profile_id="b", name="B", backend="cursor_local")
        >>> [p.profile_id for p in list_profiles(store)]
        ['a', 'b']
        >>> store.close()
    """
    rows = store.conn.execute(
        """SELECT profile_id, name, backend, model, agent, skills, scope, created_at, updated_at
           FROM profiles ORDER BY created_at""",
    ).fetchall()
    return [_row_to_profile(r) for r in rows]


def delete_profile(store: ProfileStore, profile_id: str) -> None:
    """Delete a profile by *profile_id*.

    Args:
        store (ProfileStore): Open profile store.
        profile_id (str): Profile to delete.

    Raises:
        KeyError: If *profile_id* does not exist.

    Examples:
        >>> store = open_profile_store(":memory:")
        >>> _ = upsert_profile(store, profile_id="del-me", name="D", backend="claude_code")
        >>> delete_profile(store, "del-me")
        >>> list_profiles(store)
        []
        >>> store.close()
    """
    existing = store.conn.execute(
        "SELECT profile_id FROM profiles WHERE profile_id = ?",
        (profile_id,),
    ).fetchone()
    if existing is None:
        raise KeyError(f"Profile not found: {profile_id!r}")
    store.conn.execute("DELETE FROM profiles WHERE profile_id = ?", (profile_id,))
    store.conn.commit()
    logger.debug("profiles: deleted profile {}", profile_id)


# ---------------------------------------------------------------------------
# Default seed
# ---------------------------------------------------------------------------

#: Default profiles to seed, keyed by backend name.
#: Each value is (profile_id, display_name, agent_override | None).
_DEFAULT_PROFILES: dict[str, tuple[str, str, str | None]] = {
    "claude_code": ("claude-wave-executor", "Claude Code — wave-plan-executor", None),
    "cursor_local": (
        "cursor-local-executor",
        "Cursor Local — wave-runner",
        ORCHESTRATOR_WAVE_AGENT,
    ),
    "cursor_cloud": ("cursor-cloud-executor", "Cursor Cloud — wave-plan-executor", None),
}


def seed_default_profiles(store: ProfileStore) -> list[str]:
    """Idempotently insert one default profile per available backend.

    Checks availability via each adapter's ``capabilities()`` call and skips
    unavailable backends.  Profiles that already exist are left unchanged
    (``upsert_profile`` preserves ``created_at`` on update but here we only
    call it when the row is absent, so existing customisations are preserved).

    Args:
        store (ProfileStore): Open profile store.

    Returns:
        list[str]: Profile IDs that were newly inserted (not already present).

    Examples:
        >>> store = open_profile_store(":memory:")
        >>> # Returns a list (may be empty if no backends available in test env)
        >>> created = seed_default_profiles(store)
        >>> isinstance(created, list)
        True
        >>> store.close()
    """
    from tripll.adapters import BACKENDS, get_adapter

    created: list[str] = []
    for backend_name, (profile_id, display_name, agent_override) in _DEFAULT_PROFILES.items():
        if backend_name not in BACKENDS:
            continue
        # Skip if already exists — preserve any operator customisations.
        existing = store.conn.execute(
            "SELECT profile_id FROM profiles WHERE profile_id = ?",
            (profile_id,),
        ).fetchone()
        if existing is not None:
            logger.debug("profiles: seed skipped existing {}", profile_id)
            continue
        # Check availability — only seed if the backend can actually run.
        try:
            adapter = get_adapter(backend_name)
            caps = adapter.capabilities()
            if not caps.available:
                logger.debug("profiles: seed skipped unavailable backend {}", backend_name)
                continue
        except Exception:
            logger.debug("profiles: seed skipped {}: adapter error", backend_name)
            continue
        upsert_profile(
            store,
            profile_id=profile_id,
            name=display_name,
            backend=backend_name,
            model=DEFAULT_MODEL,
            agent=agent_override or DEFAULT_AGENT,
        )
        created.append(profile_id)
        logger.info("profiles: seeded default profile {}", profile_id)
    return created


def control_plane_db_path(runs_root: Path) -> Path:
    """Return the path to the global control-plane database.

    Args:
        runs_root (Path): The tripll runs root directory.

    Returns:
        Path: ``<runs_root>/control-plane.db``.

    Examples:
        >>> from pathlib import Path
        >>> control_plane_db_path(Path("/tmp/runs"))
        PosixPath('/tmp/runs/control-plane.db')
    """
    return runs_root / "control-plane.db"
