import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._base import created_at_col, uuid_pk


class Draft(Base):
    """An automation-generated reply draft awaiting human review.

    Drafts are tenant-scoped, status-tracked, and NEVER auto-sent. There is
    no endpoint in Pioneer that posts to the source channel; the user is
    expected to copy the body or open the source thread to send manually.

    SCALE: today drafts live in PG. At larger volumes archive `dismissed`
    rows to an audit-only store after N days and keep `pending`/`edited` hot.
    """

    __tablename__ = "drafts"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    automation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("automations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Source channel + opaque thread/message ref so a future provider can
    # link back to the original conversation (LinkedIn DM URL, Gmail
    # message id, etc.).
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    thread_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    recipient: Mapped[str | None] = mapped_column(String(255), nullable=True)

    incoming_excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    draft_body: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # pending | edited | dismissed
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = created_at_col()
