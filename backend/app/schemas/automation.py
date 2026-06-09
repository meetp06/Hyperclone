import uuid

from pydantic import BaseModel, ConfigDict


class AutomationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    type: str
    enabled: bool


class AutomationPatch(BaseModel):
    enabled: bool
