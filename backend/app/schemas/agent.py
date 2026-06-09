import uuid

from pydantic import BaseModel, ConfigDict


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    provider: str
    status: str
