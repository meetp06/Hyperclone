import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    plan: str
    created_at: datetime


class UsageRead(BaseModel):
    period: str
    tokens_used: int
