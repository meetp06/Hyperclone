import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MemoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    body: str = Field(min_length=1)
    source: str = Field(default="manual", max_length=64)


class MemoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workspace_id: uuid.UUID
    author_user_id: uuid.UUID | None
    title: str
    body: str
    source: str
    sensitivity: str = "internal"
    collection: str = "manual"
    created_at: datetime


class SearchHit(BaseModel):
    """Discriminated by `kind`: 'memory' or 'document'.

    For 'memory' kind, `memory` is populated.
    For 'document' kind, `document_*` and `chunk_*` are populated.
    """

    kind: str
    score: float
    memory: MemoryRead | None = None
    # Document/chunk hits
    document_id: uuid.UUID | None = None
    document_title: str | None = None
    document_url: str | None = None
    document_provider: str | None = None
    chunk_index: int | None = None
    chunk_text: str | None = None


class ChatRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2048)
    top_k: int = Field(default=5, ge=1, le=25)
    stream: bool = Field(default=False)


class ChatResponse(BaseModel):
    answer: str
    hits: list[SearchHit]


class ChatSource(BaseModel):
    cite_id: str
    kind: str
    id: uuid.UUID
    title: str
    url: str | None
    collection: str
    sensitivity: str


class ChatUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    provider: str
    model: str
