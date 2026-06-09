import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DraftRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    automation_id: uuid.UUID
    channel: str
    thread_ref: str | None
    recipient: str | None
    incoming_excerpt: str
    draft_body: str
    status: str
    created_at: datetime
    updated_at: datetime


class DraftPatch(BaseModel):
    draft_body: str | None = Field(default=None, max_length=20_000)
    status: str | None = Field(default=None, pattern="^(pending|edited|dismissed)$")


class AutomationRunEnqueued(BaseModel):
    job_id: str
