import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ConnectorRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    provider: str
    status: str
    account_label: str | None
    last_synced_at: datetime | None
    created_at: datetime


class OAuthStartResponse(BaseModel):
    authorize_url: str
    state: str


class SyncEnqueuedResponse(BaseModel):
    job_id: str


class SyncStatusResponse(BaseModel):
    connector_id: uuid.UUID
    connector_status: str
    last_synced_at: datetime | None
    run_id: uuid.UUID | None
    run_status: str | None
    docs_seen: int
    docs_ingested: int
    chunks_written: int
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
