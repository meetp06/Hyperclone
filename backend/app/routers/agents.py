from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_workspace
from app.models import Agent, Workspace
from app.schemas.agent import AgentRead

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=list[AgentRead])
def list_agents(
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> list[AgentRead]:
    rows = list(
        db.scalars(
            select(Agent).where(Agent.workspace_id == ws.id).order_by(Agent.provider)
        )
    )
    return [AgentRead.model_validate(r) for r in rows]
