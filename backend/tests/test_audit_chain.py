"""Audit-chain hash tests — pure functions, no DB.

The DB-side tamper test (advisory lock + trigger bypass + verify) lives
in the integration smoke run; this file pins the hash semantics so
upstream refactors can't silently break the chain.
"""

from __future__ import annotations

import uuid

import pytest

from app.access import audit_chain as ac

SECRET = b"unit-test-secret-not-from-env"
WS = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _entry(seq: int, *, extra: dict | None = None) -> dict:
    return ac._payload(
        seq=seq,
        workspace_id=WS,
        principal_type="user",
        principal_id=uuid.UUID("44444444-4444-4444-4444-444444444444"),
        action="memory.search",
        resource_type="memory",
        resource_id=None,
        decision="allow",
        scope={"q": f"seq-{seq}", **(extra or {})},
        created_at=None,
    )


def test_canonical_is_stable_under_key_order():
    a = {"b": 2, "a": 1, "c": {"y": 9, "x": 8}}
    b = {"a": 1, "b": 2, "c": {"x": 8, "y": 9}}
    assert ac.canonical(a) == ac.canonical(b)


def test_chain_hash_changes_when_any_field_changes():
    h1 = ac.chain_hash(ac.GENESIS, _entry(1), secret=SECRET)
    h2 = ac.chain_hash(ac.GENESIS, _entry(1, extra={"x": 1}), secret=SECRET)
    assert h1 != h2


def test_chain_hash_changes_when_secret_changes():
    p = _entry(1)
    h1 = ac.chain_hash(ac.GENESIS, p, secret=SECRET)
    h2 = ac.chain_hash(ac.GENESIS, p, secret=b"other-secret")
    assert h1 != h2


def test_chain_propagates_prev_hash():
    p1, p2 = _entry(1), _entry(2)
    h1 = ac.chain_hash(ac.GENESIS, p1, secret=SECRET)
    h2 = ac.chain_hash(h1, p2, secret=SECRET)
    # Recompute h2 from genesis on a different middle payload — must mismatch.
    fake_mid = _entry(1, extra={"tampered": 1})
    fake_h1 = ac.chain_hash(ac.GENESIS, fake_mid, secret=SECRET)
    fake_h2 = ac.chain_hash(fake_h1, p2, secret=SECRET)
    assert h2 != fake_h2


@pytest.mark.parametrize("seq", [1, 2, 17, 9999])
def test_chain_hash_deterministic(seq: int):
    p = _entry(seq)
    a = ac.chain_hash(ac.GENESIS, p, secret=SECRET)
    b = ac.chain_hash(ac.GENESIS, p, secret=SECRET)
    assert a == b
