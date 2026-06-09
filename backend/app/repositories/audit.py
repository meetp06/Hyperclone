"""Legacy AuditRepo facade.

Phase 3 funnels writes through `app.access.audit_chain.append` so every
audit row is hash-chained. This facade keeps the old call sites unchanged.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.access import audit_chain


class AuditRepo:
    def __init__(self, db: Session) -> None:
        self.db = db

    def log(
        self,
        *,
        workspace_id: uuid.UUID,
        actor_user_id: uuid.UUID | None,
        action: str,
        resource_type: str,
        resource_id: uuid.UUID | None = None,
        decision: str = "allow",
        scope: dict | None = None,
    ) -> None:
        audit_chain.append(
            self.db,
            workspace_id=workspace_id,
            principal_type="user" if actor_user_id else "system",
            principal_id=actor_user_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            decision=decision,
            scope=scope or {},
        )
