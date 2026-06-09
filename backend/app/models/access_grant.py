import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._base import created_at_col, uuid_pk


class AccessGrant(Base):
    """Deny-by-default: absence of a grant for a principal = no access.

    `sensitivity_max` is the highest sensitivity the principal may read
    (mapped via `policy.SENSITIVITY_RANK`; e.g. internal=1 ⇒ may read
    public+internal). `collections` is an allow-list of buckets; the
    literal element `"*"` is the explicit wildcard. `actions` is a
    string list ("read", "write").
    """

    __tablename__ = "access_grants"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "principal_type", "principal_id",
            name="uq_grant_workspace_principal",
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" | "agent"
    principal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    # Ordinal: 0=public, 1=internal, 2=restricted. -1 = no read access.
    sensitivity_max: Mapped[int] = mapped_column(Integer, nullable=False, default=-1)
    collections: Mapped[list[str]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    actions: Mapped[list[str]] = mapped_column(ARRAY(String(16)), nullable=False, default=list)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = created_at_col()
