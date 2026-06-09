"""One-shot: recompute the audit chain for every existing row using the
runtime's current canonical-payload function.

Phase-3's first migration backfilled the chain with `created_at.isoformat()`
which produces a tz-suffixed string. The runtime later switched to a
microsecond-precision tz-naive form (`_normalize_dt`) so the verifier
agrees with the inserter. This script disables the immutability trigger,
recomputes every row's `prev_hash` + `entry_hash` in seq order per
workspace, then re-enables the trigger.

Safe to run multiple times — idempotent because we recompute from scratch.

Run:
    cd backend && uv run python scripts/_rebuild_audit_chain.py
"""

from __future__ import annotations

from sqlalchemy import text

from app.access.audit_chain import GENESIS, _payload, chain_hash
from app.db import SessionLocal


def main() -> None:
    db = SessionLocal()
    try:
        db.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_modify"))
        rows = db.execute(
            text(
                "SELECT id, workspace_id, seq, principal_type, principal_id, action, "
                "resource_type, resource_id, decision, scope, created_at "
                "FROM audit_log ORDER BY workspace_id, seq"
            )
        ).mappings().all()

        prev_by_ws: dict = {}
        for r in rows:
            ws = r["workspace_id"]
            prev_hash = prev_by_ws.get(ws, GENESIS)
            payload = _payload(
                seq=int(r["seq"]),
                workspace_id=ws,
                principal_type=r["principal_type"],
                principal_id=r["principal_id"],
                action=r["action"],
                resource_type=r["resource_type"],
                resource_id=r["resource_id"],
                decision=r["decision"],
                scope=r["scope"] or {},
                created_at=r["created_at"],
            )
            entry_hash = chain_hash(prev_hash, payload)
            db.execute(
                text(
                    "UPDATE audit_log SET prev_hash = :p, entry_hash = :e WHERE id = :id"
                ),
                {"p": prev_hash, "e": entry_hash, "id": r["id"]},
            )
            prev_by_ws[ws] = entry_hash

        db.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_modify"))
        db.commit()

        from app.access.audit_chain import verify
        from app.models import Workspace
        for ws in db.scalars(__import__("sqlalchemy").select(Workspace)).all():
            r = verify(db, ws.id)
            print(f"workspace={ws.id} ok={r.ok} total={r.total} broken_at={r.broken_at_seq}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
