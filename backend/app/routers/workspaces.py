from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_workspace
from app.models import UsageCounter, Workspace
from app.schemas.workspace import UsageRead, WorkspaceRead

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.get("/current", response_model=WorkspaceRead)
def get_current(ws: Workspace = Depends(current_workspace)) -> WorkspaceRead:
    return WorkspaceRead.model_validate(ws)


@router.get("/current/usage", response_model=UsageRead)
def get_usage(
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> UsageRead:
    period = datetime.now(UTC).strftime("%Y-%m")
    row = db.get(UsageCounter, {"workspace_id": ws.id, "period": period})
    return UsageRead(period=period, tokens_used=row.tokens_used if row else 0)
