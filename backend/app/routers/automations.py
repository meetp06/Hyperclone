import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user, current_workspace
from app.models import Automation, AutomationRun, User, Workspace
from app.repositories.audit import AuditRepo
from app.schemas.automation import AutomationPatch, AutomationRead
from app.schemas.draft import AutomationRunEnqueued
from app.services.queue import get_pool

router = APIRouter(prefix="/automations", tags=["automations"])


@router.get("", response_model=list[AutomationRead])
def list_automations(
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> list[AutomationRead]:
    rows = list(
        db.scalars(
            select(Automation)
            .where(Automation.workspace_id == ws.id)
            .order_by(Automation.type)
        )
    )
    return [AutomationRead.model_validate(r) for r in rows]


@router.post("/{automation_id}/run", response_model=AutomationRunEnqueued)
async def run_automation_now(
    automation_id: uuid.UUID,
    user: User = Depends(current_user),
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> AutomationRunEnqueued:
    """Enqueue a manual run for testing. The worker job processes ALL
    enabled automations in the workspace — automation_id is just the
    audit trail anchor here.
    """
    row = db.scalar(
        select(Automation).where(
            Automation.id == automation_id, Automation.workspace_id == ws.id
        )
    )
    if row is None:
        raise HTTPException(404, "automation not found")
    AuditRepo(db).log(
        workspace_id=ws.id,
        actor_user_id=user.id,
        action="automation.run.enqueue",
        resource_type="automation",
        resource_id=row.id,
    )
    db.commit()
    pool = await get_pool()
    job = await pool.enqueue_job("run_automations", str(ws.id))
    return AutomationRunEnqueued(job_id=job.job_id if job else "unknown")


@router.get("/{automation_id}/runs", response_model=list[dict])
def list_automation_runs(
    automation_id: uuid.UUID,
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
    limit: int = 5,
) -> list[dict]:
    rows = list(
        db.scalars(
            select(AutomationRun)
            .where(
                AutomationRun.automation_id == automation_id,
                AutomationRun.workspace_id == ws.id,
            )
            .order_by(AutomationRun.created_at.desc())
            .limit(limit)
        )
    )
    return [
        {
            "id": str(r.id),
            "status": r.status,
            "inbound_seen": r.inbound_seen,
            "drafts_created": r.drafts_created,
            "tokens_in": r.tokens_in,
            "tokens_out": r.tokens_out,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "error": r.error,
        }
        for r in rows
    ]


@router.patch("/{automation_id}", response_model=AutomationRead)
def patch_automation(
    automation_id: uuid.UUID,
    patch: AutomationPatch,
    user: User = Depends(current_user),
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> AutomationRead:
    row = db.scalar(
        select(Automation).where(
            Automation.id == automation_id, Automation.workspace_id == ws.id
        )
    )
    if row is None:
        raise HTTPException(404, "automation not found")
    row.enabled = patch.enabled
    db.flush()
    AuditRepo(db).log(
        workspace_id=ws.id,
        actor_user_id=user.id,
        action="automation.toggle",
        resource_type="automation",
        resource_id=row.id,
    )
    db.commit()
    db.refresh(row)
    return AutomationRead.model_validate(row)
