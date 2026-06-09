import uuid

from sqlalchemy import BigInteger, ForeignKey, PrimaryKeyConstraint, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class UsageCounter(Base):
    __tablename__ = "usage_counters"
    __table_args__ = (PrimaryKeyConstraint("workspace_id", "period", name="pk_usage_counters"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    # YYYY-MM
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    tokens_used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
