"""Append-only hash-chained audit log.

Per-workspace seq + HMAC-SHA256 chain. Inserts serialize via a Postgres
advisory lock keyed on `('audit:' || workspace_id)` so concurrent writers
can't fight over `seq` or `prev_hash`.

Verification recomputes the chain from genesis (zero-hash) and returns
the first seq where it breaks, if any.

SCALE:
- One advisory lock per workspace = fine for thousands of writes/sec.
- For very high write rates per workspace, batch entries onto a per-WS
  Redis stream and have one writer build the chain async.
- Periodically anchor the head hash to S3 / a transparency log for
  cross-system tamper evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import AuditLog

GENESIS = b"\x00" * 32


def _secret() -> bytes:
    s = get_settings()
    if not s.audit_hmac_key or s.audit_hmac_key.startswith("REPLACE_ME"):
        raise RuntimeError("AUDIT_HMAC_KEY is not set")
    return s.audit_hmac_key.encode("utf-8")


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def chain_hash(prev: bytes, payload: dict[str, Any], *, secret: bytes | None = None) -> bytes:
    return hmac.new(secret or _secret(), prev + canonical(payload), hashlib.sha256).digest()


def _normalize_dt(dt: datetime | None) -> str | None:
    """Stable, timezone-agnostic representation that survives the PG
    timestamptz round-trip. We pin it to UTC and strip the offset so
    inserter (`datetime.now(UTC)`) and verifier (PG returns tz-aware)
    produce the same canonical bytes.
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(UTC).replace(tzinfo=None)
    # Microsecond precision matches PG's timestamptz storage.
    return dt.isoformat(timespec="microseconds")


def _payload(
    *,
    seq: int,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None,
    decision: str,
    scope: dict[str, Any],
    created_at: datetime,
) -> dict[str, Any]:
    """The canonical field set hashed into the chain. Order doesn't matter
    (json.dumps sorts keys), but the *set* must be stable across releases.
    Adding a field = breaking change; bump a chain-version on the workspace
    before rolling it out.
    """
    return {
        "seq": seq,
        "workspace_id": str(workspace_id),
        "principal_type": principal_type,
        "principal_id": str(principal_id) if principal_id else None,
        "action": action,
        "resource_type": resource_type,
        "resource_id": str(resource_id) if resource_id else None,
        "decision": decision,
        "scope": scope or {},
        "created_at": _normalize_dt(created_at),
    }


def append(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID | None,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | None = None,
    decision: str = "allow",
    scope: dict[str, Any] | None = None,
    actor_user_id: uuid.UUID | None = None,
) -> AuditLog:
    """Insert one chained audit entry. Caller commits the transaction."""
    scope = scope or {}

    # Workspace-scoped advisory lock — held until the transaction ends.
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
        {"k": f"audit:{workspace_id}"},
    )

    prev = db.execute(
        text(
            "SELECT seq, entry_hash FROM audit_log "
            "WHERE workspace_id = :w ORDER BY seq DESC LIMIT 1"
        ),
        {"w": str(workspace_id)},
    ).first()
    if prev is None:
        prev_seq, prev_hash = 0, GENESIS
    else:
        prev_seq, prev_hash = int(prev[0]), bytes(prev[1])

    seq = prev_seq + 1
    now = datetime.now(UTC)

    payload = _payload(
        seq=seq,
        workspace_id=workspace_id,
        principal_type=principal_type,
        principal_id=principal_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        decision=decision,
        scope=scope,
        created_at=now,
    )
    entry_hash = chain_hash(prev_hash, payload)

    row = AuditLog(
        workspace_id=workspace_id,
        seq=seq,
        principal_type=principal_type,
        principal_id=principal_id,
        actor_user_id=actor_user_id or (principal_id if principal_type == "user" else None),
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        decision=decision,
        scope=scope,
        prev_hash=prev_hash,
        entry_hash=entry_hash,
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row


@dataclass
class VerifyResult:
    ok: bool
    total: int
    broken_at_seq: int | None
    head_hash_hex: str


def verify(db: Session, workspace_id: uuid.UUID) -> VerifyResult:
    """Walk the chain from genesis. Return the first seq that breaks
    (if any), the total entries, and the recomputed head hash.
    """
    rows = db.execute(
        text(
            "SELECT seq, principal_type, principal_id, action, resource_type, "
            "resource_id, decision, scope, prev_hash, entry_hash, created_at "
            "FROM audit_log WHERE workspace_id = :w ORDER BY seq ASC"
        ),
        {"w": str(workspace_id)},
    ).mappings().all()

    prev_hash = GENESIS
    broken_at: int | None = None
    for r in rows:
        payload = _payload(
            seq=int(r["seq"]),
            workspace_id=workspace_id,
            principal_type=r["principal_type"],
            principal_id=r["principal_id"],
            action=r["action"],
            resource_type=r["resource_type"],
            resource_id=r["resource_id"],
            decision=r["decision"],
            scope=r["scope"] or {},
            created_at=r["created_at"],
        )
        expected = chain_hash(prev_hash, payload)
        stored_prev = bytes(r["prev_hash"]) if r["prev_hash"] is not None else GENESIS
        stored_entry = bytes(r["entry_hash"]) if r["entry_hash"] is not None else b""
        if stored_prev != prev_hash or stored_entry != expected:
            broken_at = int(r["seq"])
            break
        prev_hash = expected

    return VerifyResult(
        ok=(broken_at is None),
        total=len(rows),
        broken_at_seq=broken_at,
        head_hash_hex=prev_hash.hex(),
    )
