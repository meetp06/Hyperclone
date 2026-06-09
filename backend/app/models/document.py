import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._base import created_at_col, uuid_pk


class Document(Base):
    """Source-of-truth row for an ingested external document.

    `external_id` is the provider's stable id (e.g. Notion page id).
    `content_hash` lets the worker skip re-embedding unchanged docs.
    Vectors for this document live in Qdrant keyed by `document_id`.

    The UNIQUE on (workspace_id, provider, external_id) is the dedup
    contract — reruns upsert, never duplicate.
    """

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider", "external_id", name="uq_documents_ws_provider_external"
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)

    title: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    url: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # Phase 3 access-control fields. Default = internal + <provider> collection.
    sensitivity: Mapped[str] = mapped_column(String(16), nullable=False, default="internal")
    collection: Mapped[str] = mapped_column(String(64), nullable=False, default="notion")

    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ingested_at: Mapped[datetime] = created_at_col()
