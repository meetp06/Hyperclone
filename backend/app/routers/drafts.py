"""Drafts endpoints — list, edit, dismiss. No send endpoint exists."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import audit_chain
from app.access.principal import Principal, principal_for_request
from app.db import get_db
from app.models import Draft
from app.schemas.draft import DraftPatch, DraftRead

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("", response_model=list[DraftRead])
def list_drafts(
    principal: Principal = Depends(principal_for_request),
    db: Session = Depends(get_db),
    status: str | None = Query(default=None, pattern="^(pending|edited|dismissed)$"),
    automation_id: uuid.UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[DraftRead]:
    stmt = (
        select(Draft)
        .where(Draft.workspace_id == principal.workspace_id)
        .order_by(Draft.created_at.desc())
        .limit(limit)
    )
    if status:
        stmt = stmt.where(Draft.status == status)
    if automation_id:
        stmt = stmt.where(Draft.automation_id == automation_id)
    rows = list(db.scalars(stmt))
    return [DraftRead.model_validate(r) for r in rows]


@router.patch("/{draft_id}", response_model=DraftRead)
def patch_draft(
    draft_id: uuid.UUID,
    req: DraftPatch,
    principal: Principal = Depends(principal_for_request),
    db: Session = Depends(get_db),
) -> DraftRead:
    row = db.scalar(
        select(Draft).where(
            Draft.id == draft_id, Draft.workspace_id == principal.workspace_id
        )
    )
    if row is None:
        raise HTTPException(404, "draft not found")

    changed: dict = {}
    if req.draft_body is not None and req.draft_body != row.draft_body:
        row.draft_body = req.draft_body
        # Editing implicitly marks it 'edited' unless caller overrides.
        if req.status is None and row.status == "pending":
            row.status = "edited"
        changed["body"] = True
    if req.status is not None and req.status != row.status:
        row.status = req.status
        changed["status"] = req.status

    if changed:
        row.updated_at = datetime.now(UTC)
        db.flush()
        audit_chain.append(
            db,
            workspace_id=principal.workspace_id,
            principal_type=principal.type,
            principal_id=principal.id,
            action="draft.update",
            resource_type="draft",
            resource_id=row.id,
            decision="allow",
            scope={"changed": changed, "status": row.status},
        )
    db.commit()
    db.refresh(row)
    return DraftRead.model_validate(row)
