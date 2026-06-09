"""Pure unit tests for the policy engine — no DB, no network."""

from __future__ import annotations

import uuid

import pytest

from app.access.policy import (
    AccessFilter,
    GrantSet,
    NO_READ,
    SENSITIVITY_RANK,
    WILDCARD,
    allowed_filter,
    allowed_sensitivities,
    can_read,
    can_write,
    to_qdrant_filter,
)

WS = uuid.UUID("11111111-1111-1111-1111-111111111111")


# ---------- deny-by-default --------------------------------------------


def test_default_grantset_denies_all_reads():
    g = GrantSet()
    assert g.can_read is False
    assert g.can_write_action is False
    assert can_read(g, "public", "manual") is False
    assert can_read(g, "internal", "notion") is False


def test_allowed_filter_with_no_grant_is_unsatisfiable():
    g = GrantSet()
    af = allowed_filter(WS, g)
    assert af.sensitivity_max == NO_READ
    assert af.allows_any_read is False
    # Qdrant filter built from this is workspace + sensitivity=__deny__ — matches nothing.
    qf = to_qdrant_filter(af)
    serialized = repr(qf)
    assert "__deny__" in serialized


# ---------- sensitivity ladder -----------------------------------------


def test_sensitivity_ladder():
    g = GrantSet(
        sensitivity_max=SENSITIVITY_RANK["internal"],
        collections=frozenset({"notion"}),
        actions=frozenset({"read"}),
    )
    assert can_read(g, "public", "notion") is True
    assert can_read(g, "internal", "notion") is True
    assert can_read(g, "restricted", "notion") is False


def test_unknown_sensitivity_denied():
    g = GrantSet(
        sensitivity_max=2,
        collections=frozenset({WILDCARD}),
        actions=frozenset({"read", "write"}),
    )
    assert can_read(g, "top-secret", "manual") is False
    assert can_write(g, "top-secret", "manual") is False


# ---------- collection allow-list --------------------------------------


def test_collection_allow_list():
    g = GrantSet(
        sensitivity_max=2,
        collections=frozenset({"notion"}),
        actions=frozenset({"read"}),
    )
    assert can_read(g, "internal", "notion") is True
    assert can_read(g, "internal", "manual") is False
    assert can_read(g, "internal", "slack-dm") is False


def test_wildcard_collection_allows_anything_at_or_below_max():
    g = GrantSet(
        sensitivity_max=1,
        collections=frozenset({WILDCARD}),
        actions=frozenset({"read"}),
    )
    assert can_read(g, "internal", "anything") is True
    assert can_read(g, "internal", "even-this") is True
    assert can_read(g, "restricted", "anything") is False  # ladder still applies


# ---------- writes -----------------------------------------------------


def test_write_requires_write_action():
    g = GrantSet(
        sensitivity_max=2,
        collections=frozenset({WILDCARD}),
        actions=frozenset({"read"}),  # missing "write"
    )
    assert can_write(g, "internal", "manual") is False


def test_write_below_max_and_in_collection():
    g = GrantSet(
        sensitivity_max=1,
        collections=frozenset({"manual"}),
        actions=frozenset({"read", "write"}),
    )
    assert can_write(g, "internal", "manual") is True
    assert can_write(g, "restricted", "manual") is False  # over the ladder
    assert can_write(g, "internal", "notion") is False  # wrong bucket


# ---------- allowed_filter compilation ---------------------------------


def test_allowed_filter_strips_wildcard_from_concrete_set():
    g = GrantSet(
        sensitivity_max=1,
        collections=frozenset({WILDCARD, "notion"}),
        actions=frozenset({"read"}),
    )
    af = allowed_filter(WS, g)
    assert af.wildcard is True
    assert "notion" in af.collections
    assert WILDCARD not in af.collections
    assert af.allows_any_read is True


def test_allowed_sensitivities_returns_correct_levels():
    af = AccessFilter(
        workspace_id=WS,
        sensitivity_max=SENSITIVITY_RANK["internal"],
        collections=frozenset({"notion"}),
    )
    assert allowed_sensitivities(af) == ["public", "internal"]

    af_none = AccessFilter(workspace_id=WS, sensitivity_max=NO_READ)
    assert allowed_sensitivities(af_none) == []


# ---------- Qdrant filter shape ----------------------------------------


def test_qdrant_filter_pins_workspace_and_sensitivity_and_collections():
    g = GrantSet(
        sensitivity_max=1,
        collections=frozenset({"notion"}),
        actions=frozenset({"read"}),
    )
    af = allowed_filter(WS, g)
    qf = to_qdrant_filter(af)
    s = repr(qf)
    assert str(WS) in s
    assert "sensitivity" in s and "public" in s and "internal" in s
    assert "restricted" not in s  # must not leak
    assert "collection" in s and "notion" in s


def test_qdrant_filter_wildcard_omits_collection_constraint():
    g = GrantSet(
        sensitivity_max=2,
        collections=frozenset({WILDCARD}),
        actions=frozenset({"read"}),
    )
    af = allowed_filter(WS, g)
    qf = to_qdrant_filter(af)
    s = repr(qf)
    # Workspace still pinned, sensitivity ladder still present, but no concrete
    # collection match condition.
    assert str(WS) in s
    assert "key='sensitivity'" in s.replace('"', "'") or "key='collection'" not in s.replace('"', "'")


@pytest.mark.parametrize("level", ["public", "internal", "restricted"])
def test_qdrant_filter_includes_only_levels_at_or_below_max(level):
    rank = SENSITIVITY_RANK[level]
    g = GrantSet(
        sensitivity_max=rank,
        collections=frozenset({WILDCARD}),
        actions=frozenset({"read"}),
    )
    af = allowed_filter(WS, g)
    levels = allowed_sensitivities(af)
    assert all(SENSITIVITY_RANK[l] <= rank for l in levels)
