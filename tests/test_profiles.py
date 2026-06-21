"""Tests for W4 agent-profile store (tripll.profiles).

Covers:
- upsert_profile / get_profile / list_profiles / delete_profile round-trips.
- Reuse guarantee: same profile ID across multiple upserts preserves created_at.
- seed_default_profiles: idempotent; only inserts when backend is available.
- ProfileRow hydration: JSON fields (skills, scope) decode correctly.
"""

from __future__ import annotations

import pytest

from tripll.profiles import (
    delete_profile,
    get_profile,
    list_profiles,
    open_profile_store,
    seed_default_profiles,
    upsert_profile,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store():  # type: ignore[no-untyped-def]
    """In-memory profile store for each test."""
    s = open_profile_store(":memory:")
    yield s
    s.close()


# ---------------------------------------------------------------------------
# 1. CRUD round-trips
# ---------------------------------------------------------------------------


def test_upsert_and_get_profile(store) -> None:  # type: ignore[no-untyped-def]
    """upsert_profile creates a row; get_profile retrieves it."""
    p = upsert_profile(
        store,
        profile_id="test-profile",
        name="Test Profile",
        backend="claude_code",
        model="claude-3-5-sonnet",
        agent="wave-plan-executor",
        skills=["skill-a"],
        scope={"foo": "bar"},
    )
    assert p.profile_id == "test-profile"
    assert p.name == "Test Profile"
    assert p.backend == "claude_code"
    assert p.model == "claude-3-5-sonnet"
    assert p.agent == "wave-plan-executor"
    assert p.skills == ["skill-a"]
    assert p.scope == {"foo": "bar"}
    assert p.created_at
    assert p.updated_at

    fetched = get_profile(store, "test-profile")
    assert fetched.profile_id == p.profile_id
    assert fetched.name == p.name
    assert fetched.skills == ["skill-a"]
    assert fetched.scope == {"foo": "bar"}


def test_list_profiles_empty(store) -> None:  # type: ignore[no-untyped-def]
    """list_profiles returns empty list when no profiles exist."""
    assert list_profiles(store) == []


def test_list_profiles_ordered(store) -> None:  # type: ignore[no-untyped-def]
    """list_profiles returns all profiles ordered by created_at."""
    upsert_profile(store, profile_id="a", name="A", backend="claude_code")
    upsert_profile(store, profile_id="b", name="B", backend="cursor_local")
    upsert_profile(store, profile_id="c", name="C", backend="cursor_cloud")
    ids = [p.profile_id for p in list_profiles(store)]
    assert ids == ["a", "b", "c"]


def test_delete_profile(store) -> None:  # type: ignore[no-untyped-def]
    """delete_profile removes the row; subsequent get raises KeyError."""
    upsert_profile(store, profile_id="del-me", name="D", backend="claude_code")
    assert get_profile(store, "del-me").profile_id == "del-me"
    delete_profile(store, "del-me")
    assert list_profiles(store) == []
    with pytest.raises(KeyError, match="del-me"):
        get_profile(store, "del-me")


def test_delete_nonexistent_profile_raises(store) -> None:  # type: ignore[no-untyped-def]
    """delete_profile raises KeyError when the profile does not exist."""
    with pytest.raises(KeyError, match="missing"):
        delete_profile(store, "missing")


def test_get_nonexistent_profile_raises(store) -> None:  # type: ignore[no-untyped-def]
    """get_profile raises KeyError when the profile does not exist."""
    with pytest.raises(KeyError, match="no-such"):
        get_profile(store, "no-such")


# ---------------------------------------------------------------------------
# 2. Reuse guarantee — same profile_id preserves created_at
# ---------------------------------------------------------------------------


def test_upsert_preserves_created_at(store) -> None:  # type: ignore[no-untyped-def]
    """Upserting an existing profile preserves the original created_at timestamp."""
    first = upsert_profile(store, profile_id="p1", name="Original", backend="claude_code")
    original_created = first.created_at

    # Update name and model.
    updated = upsert_profile(
        store,
        profile_id="p1",
        name="Updated",
        backend="claude_code",
        model="claude-opus",
    )
    assert updated.profile_id == "p1"
    assert updated.name == "Updated"
    assert updated.model == "claude-opus"
    # created_at must be unchanged.
    assert updated.created_at == original_created
    # updated_at must be >= created_at (may be equal if clock resolution is low).
    assert updated.updated_at >= original_created


def test_same_profile_reused_across_upserts(store) -> None:  # type: ignore[no-untyped-def]
    """Multiple upserts with the same ID do not create duplicate rows."""
    for i in range(5):
        upsert_profile(store, profile_id="stable", name=f"Iter {i}", backend="claude_code")
    profiles = list_profiles(store)
    assert len(profiles) == 1
    assert profiles[0].name == "Iter 4"


# ---------------------------------------------------------------------------
# 3. JSON field hydration
# ---------------------------------------------------------------------------


def test_skills_round_trip(store) -> None:  # type: ignore[no-untyped-def]
    """skills list is stored as JSON and decoded back to a list."""
    skills = ["web-search", "code-exec", "file-read"]
    upsert_profile(store, profile_id="sk", name="Sk", backend="claude_code", skills=skills)
    p = get_profile(store, "sk")
    assert isinstance(p.skills, list)
    assert p.skills == skills


def test_scope_round_trip(store) -> None:  # type: ignore[no-untyped-def]
    """scope dict is stored as JSON and decoded back to a dict."""
    scope: dict[str, object] = {"toolchain": "/usr/local/bin", "extra_dirs": ["src/", "tests/"]}
    upsert_profile(store, profile_id="sc", name="Sc", backend="claude_code", scope=scope)
    p = get_profile(store, "sc")
    assert isinstance(p.scope, dict)
    assert p.scope == scope


def test_empty_skills_and_scope_defaults(store) -> None:  # type: ignore[no-untyped-def]
    """Omitting skills and scope defaults to empty list and dict."""
    upsert_profile(store, profile_id="defaults", name="D", backend="claude_code")
    p = get_profile(store, "defaults")
    assert p.skills == []
    assert p.scope == {}


# ---------------------------------------------------------------------------
# 4. seed_default_profiles — idempotency
# ---------------------------------------------------------------------------


def test_seed_default_profiles_idempotent(store) -> None:  # type: ignore[no-untyped-def]
    """Seeding twice does not create duplicate profiles."""
    seed_default_profiles(store)
    count_after_first = len(list_profiles(store))
    seed_default_profiles(store)
    count_after_second = len(list_profiles(store))
    assert count_after_second == count_after_first


def test_seed_returns_list(store) -> None:  # type: ignore[no-untyped-def]
    """seed_default_profiles returns a list of newly created profile IDs."""
    created = seed_default_profiles(store)
    assert isinstance(created, list)
    # Second call returns empty (all already seeded).
    created2 = seed_default_profiles(store)
    assert created2 == []


def test_seeded_profiles_not_created_twice(store) -> None:  # type: ignore[no-untyped-def]
    """Profiles seeded on first call are not returned on second call."""
    first = seed_default_profiles(store)
    second = seed_default_profiles(store)
    # Any profile in second was NOT in first (since they already existed).
    for pid in second:
        assert pid not in first


def test_seed_preserves_existing_customisation(store) -> None:  # type: ignore[no-untyped-def]
    """seed_default_profiles skips profiles that already exist (preserves customisation)."""
    # Pre-seed with a custom model.
    upsert_profile(
        store,
        profile_id="claude-wave-executor",
        name="Custom Claude",
        backend="claude_code",
        model="claude-opus-custom",
    )
    # Seed should skip this profile since it already exists.
    seed_default_profiles(store)
    # The custom model must be preserved.
    p = get_profile(store, "claude-wave-executor")
    assert p.model == "claude-opus-custom"
    assert p.name == "Custom Claude"


# ---------------------------------------------------------------------------
# 5. ProfileRow dataclass
# ---------------------------------------------------------------------------


def test_profile_row_is_frozen(store) -> None:  # type: ignore[no-untyped-def]
    """ProfileRow is a frozen dataclass — attributes cannot be mutated."""
    p = upsert_profile(store, profile_id="frozen", name="F", backend="claude_code")
    with pytest.raises((AttributeError, TypeError)):
        p.name = "mutated"  # type: ignore[misc]
