from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.access import audit_chain
from app.access.policy import allowed_filter, can_write
from app.access.principal import Principal, principal_for_request
from app.db import get_db
from app.schemas.memory import MemoryCreate, MemoryRead
from app.services import memory as memory_service

router = APIRouter(prefix="/memories", tags=["memories"])


@router.post("", response_model=MemoryRead, status_code=201)
def create_memory(
    req: MemoryCreate,
    principal: Principal = Depends(principal_for_request),
    db: Session = Depends(get_db),
) -> MemoryRead:
    sensitivity = "internal"
    collection = "manual"
    if not can_write(principal.grants, sensitivity, collection):
        # Record the denial in the chain too — not just successes.
        audit_chain.append(
            db,
            workspace_id=principal.workspace_id,
            principal_type=principal.type,
            principal_id=principal.id,
            action="memory.write",
            resource_type="memory",
            decision="deny",
            scope={"sensitivity": sensitivity, "collection": collection, "reason": "no_write_grant"},
        )
        db.commit()
        raise HTTPException(403, "no write grant on (internal/manual)")

    m = memory_service.write_memory(
        db=db,
        workspace_id=principal.workspace_id,
        author_user_id=principal.id if principal.type == "user" else None,
        principal_type=principal.type,
        principal_id=principal.id,
        title=req.title,
        body=req.body,
        source=req.source,
        sensitivity=sensitivity,
        collection=collection,
    )
    return MemoryRead.model_validate(m)


@router.get("", response_model=list[MemoryRead])
def list_memories(
    principal: Principal = Depends(principal_for_request),
    db: Session = Depends(get_db),
    limit: int = 100,
) -> list[MemoryRead]:
    af = allowed_filter(principal.workspace_id, principal.grants)
    rows = memory_service.list_recent(
        db=db,
        workspace_id=principal.workspace_id,
        principal_type=principal.type,
        principal_id=principal.id,
        access_filter=af,
        limit=limit,
    )
    return [MemoryRead.model_validate(m) for m in rows]
