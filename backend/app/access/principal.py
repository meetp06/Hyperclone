"""Principal resolver — unifies user-JWT and agent-key auth.

A single dependency turns either credential into a `Principal` carrying
workspace, type, id, and the compiled `GrantSet`. Routers depend on this
once and never branch on "user vs agent" themselves.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.grants import load_grant
from app.access.policy import GrantSet
from app.access.tokens import hash_key
from app.db import get_db
from app.models import AgentKey, Membership, User, Workspace
from app.services.auth import decode_token


@dataclass(frozen=True)
class Principal:
    type: Literal["user", "agent"]
    id: uuid.UUID
    workspace_id: uuid.UUID
    grants: GrantSet


def _bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip()


def _resolve_user(token: str, db: Session) -> Principal | None:
    try:
        payload = decode_token(token)
    except Exception:  # noqa: BLE001
        return None
    try:
        uid = uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None
    user = db.scalar(select(User).where(User.id == uid))
    if user is None:
        return None
    m = db.scalar(
        select(Membership).where(Membership.user_id == user.id).order_by(Membership.id).limit(1)
    )
    if m is None:
        return None
    ws = db.get(Workspace, m.workspace_id)
    if ws is None:
        return None
    grants = load_grant(
        db, workspace_id=ws.id, principal_type="user", principal_id=user.id
    )
    return Principal(type="user", id=user.id, workspace_id=ws.id, grants=grants)


def _resolve_agent(token: str, db: Session) -> Principal | None:
    if not token.startswith("pk_"):
        return None
    h = hash_key(token)
    row = db.scalar(select(AgentKey).where(AgentKey.key_hash == h))
    if row is None or row.revoked_at is not None:
        return None
    # Bump last_used_at — best-effort; failure here must not block auth.
    row.last_used_at = datetime.utcnow()
    db.flush()
    grants = load_grant(
        db, workspace_id=row.workspace_id, principal_type="agent", principal_id=row.agent_id
    )
    return Principal(
        type="agent",
        id=row.agent_id,
        workspace_id=row.workspace_id,
        grants=grants,
    )


def principal_for_request(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> Principal:
    token = _bearer(authorization)
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing bearer token")
    # Try agent first (cheap hash lookup); fall back to JWT decode.
    p = _resolve_agent(token, db) or _resolve_user(token, db)
    if p is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    return p


def require_user(principal: Principal = Depends(principal_for_request)) -> Principal:
    if principal.type != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "user-only endpoint")
    return principal
