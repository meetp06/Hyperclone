import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ---------- Audit ----------


class AuditEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    seq: int
    principal_type: str
    principal_id: uuid.UUID | None
    action: str
    resource_type: str
    resource_id: uuid.UUID | None
    decision: str
    scope: dict
    created_at: datetime


class AuditVerifyResponse(BaseModel):
    ok: bool
    total: int
    broken_at_seq: int | None
    head_hash: str


# ---------- Grants ----------


class GrantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    principal_type: str
    principal_id: uuid.UUID
    sensitivity_max: int
    collections: list[str]
    actions: list[str]


class GrantUpdate(BaseModel):
    sensitivity_max: int = Field(ge=-1, le=2)
    collections: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)


# ---------- Agent keys ----------


class AgentKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    key_prefix: str
    created_at: datetime
    last_used_at: datetime | None
    revoked_at: datetime | None


class AgentKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class AgentKeyCreated(AgentKeyRead):
    # Plaintext returned ONCE on creation — never on subsequent reads.
    plaintext: str
