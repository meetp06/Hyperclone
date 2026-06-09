"""Phase-3 access-control endpoints: audit, grants, agent keys."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import audit_chain
from app.access.grants import load_grant, revoke_grant, upsert_grant
from app.access.principal import Principal, principal_for_request, require_user
from app.access.tokens import generate_key
from app.db import get_db
from app.models import AccessGrant, Agent, AgentKey, AuditLog
from app.schemas.access import (
    AgentKeyCreate,
    AgentKeyCreated,
    AgentKeyRead,
    AuditEntryRead,
    AuditVerifyResponse,
    GrantRead,
    GrantUpdate,
)


# ---------- Audit ----------

audit_router = APIRouter(prefix="/audit", tags=["audit"])


@audit_router.get("", response_model=list[AuditEntryRead])
def list_audit(
    principal: Principal = Depends(principal_for_request),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    before_seq: int | None = Query(default=None, ge=1),
) -> list[AuditEntryRead]:
    stmt = (
        select(AuditLog)
        .where(AuditLog.workspace_id == principal.workspace_id)
        .order_by(AuditLog.seq.desc())
        .limit(limit)
    )
    if before_seq is not None:
        stmt = stmt.where(AuditLog.seq < before_seq)
    rows = list(db.scalars(stmt))
    return [AuditEntryRead.model_validate(r) for r in rows]


@audit_router.get("/verify", response_model=AuditVerifyResponse)
def verify_audit(
    principal: Principal = Depends(principal_for_request),
    db: Session = Depends(get_db),
) -> AuditVerifyResponse:
    r = audit_chain.verify(db, principal.workspace_id)
    return AuditVerifyResponse(
        ok=r.ok, total=r.total, broken_at_seq=r.broken_at_seq, head_hash=r.head_hash_hex
    )


# ---------- Agents access (grants + keys) ----------

agents_access_router = APIRouter(prefix="/agents", tags=["access"])


def _agent_owned_by_workspace(db: Session, agent_id: uuid.UUID, workspace_id: uuid.UUID) -> Agent:
    a = db.scalar(
        select(Agent).where(Agent.id == agent_id, Agent.workspace_id == workspace_id)
    )
    if a is None:
        raise HTTPException(404, "agent not found")
    return a


@agents_access_router.get("/{agent_id}/access", response_model=GrantRead | None)
def get_access(
    agent_id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
) -> GrantRead | None:
    _agent_owned_by_workspace(db, agent_id, principal.workspace_id)
    row = db.scalar(
        select(AccessGrant).where(
            AccessGrant.workspace_id == principal.workspace_id,
            AccessGrant.principal_type == "agent",
            AccessGrant.principal_id == agent_id,
        )
    )
    if row is None:
        return None
    return GrantRead.model_validate(row)


@agents_access_router.put("/{agent_id}/access", response_model=GrantRead)
def put_access(
    agent_id: uuid.UUID,
    req: GrantUpdate,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
) -> GrantRead:
    _agent_owned_by_workspace(db, agent_id, principal.workspace_id)
    row = upsert_grant(
        db,
        workspace_id=principal.workspace_id,
        principal_type="agent",
        principal_id=agent_id,
        sensitivity_max=req.sensitivity_max,
        collections=req.collections,
        actions=req.actions,
        created_by=principal.id,
    )
    audit_chain.append(
        db,
        workspace_id=principal.workspace_id,
        principal_type=principal.type,
        principal_id=principal.id,
        action="access.grant.set",
        resource_type="agent",
        resource_id=agent_id,
        decision="allow",
        scope={
            "sensitivity_max": req.sensitivity_max,
            "collections": req.collections,
            "actions": req.actions,
        },
    )
    db.commit()
    db.refresh(row)
    return GrantRead.model_validate(row)


@agents_access_router.delete("/{agent_id}/access", status_code=204)
def delete_access(
    agent_id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
) -> None:
    _agent_owned_by_workspace(db, agent_id, principal.workspace_id)
    revoke_grant(
        db,
        workspace_id=principal.workspace_id,
        principal_type="agent",
        principal_id=agent_id,
    )
    audit_chain.append(
        db,
        workspace_id=principal.workspace_id,
        principal_type=principal.type,
        principal_id=principal.id,
        action="access.grant.revoke",
        resource_type="agent",
        resource_id=agent_id,
        decision="allow",
        scope={},
    )
    db.commit()


@agents_access_router.get("/{agent_id}/keys", response_model=list[AgentKeyRead])
def list_keys(
    agent_id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
) -> list[AgentKeyRead]:
    _agent_owned_by_workspace(db, agent_id, principal.workspace_id)
    rows = list(
        db.scalars(
            select(AgentKey)
            .where(AgentKey.agent_id == agent_id)
            .order_by(AgentKey.created_at.desc())
        )
    )
    return [AgentKeyRead.model_validate(r) for r in rows]


@agents_access_router.post("/{agent_id}/keys", response_model=AgentKeyCreated, status_code=201)
def create_key(
    agent_id: uuid.UUID,
    req: AgentKeyCreate,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
) -> AgentKeyCreated:
    _agent_owned_by_workspace(db, agent_id, principal.workspace_id)
    plaintext, key_hash, prefix = generate_key()
    row = AgentKey(
        workspace_id=principal.workspace_id,
        agent_id=agent_id,
        name=req.name,
        key_hash=key_hash,
        key_prefix=prefix,
    )
    db.add(row)
    db.flush()
    audit_chain.append(
        db,
        workspace_id=principal.workspace_id,
        principal_type=principal.type,
        principal_id=principal.id,
        action="agent.key.create",
        resource_type="agent_key",
        resource_id=row.id,
        decision="allow",
        scope={"agent_id": str(agent_id), "name": req.name, "prefix": prefix},
    )
    db.commit()
    db.refresh(row)
    return AgentKeyCreated(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        plaintext=plaintext,
    )


@agents_access_router.delete("/{agent_id}/keys/{key_id}", status_code=204)
def revoke_key(
    agent_id: uuid.UUID,
    key_id: uuid.UUID,
    principal: Principal = Depends(require_user),
    db: Session = Depends(get_db),
) -> None:
    _agent_owned_by_workspace(db, agent_id, principal.workspace_id)
    row = db.scalar(
        select(AgentKey).where(
            AgentKey.id == key_id,
            AgentKey.agent_id == agent_id,
            AgentKey.workspace_id == principal.workspace_id,
        )
    )
    if row is None:
        raise HTTPException(404, "key not found")
    if row.revoked_at is None:
        row.revoked_at = datetime.now(UTC)
        db.flush()
    audit_chain.append(
        db,
        workspace_id=principal.workspace_id,
        principal_type=principal.type,
        principal_id=principal.id,
        action="agent.key.revoke",
        resource_type="agent_key",
        resource_id=key_id,
        decision="allow",
        scope={"agent_id": str(agent_id), "prefix": row.key_prefix},
    )
    db.commit()
