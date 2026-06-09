import uuid
from datetime import datetime

from sqlalchemy import BigInteger, ForeignKey, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._base import created_at_col, uuid_pk


class AuditLog(Base):
    """Append-only, hash-chained audit log.

    Phase-3 contract:
    - The DB enforces immutability via a BEFORE UPDATE/DELETE trigger.
    - Each row's `entry_hash = HMAC(secret, prev_hash || canonical_json(fields))`.
    - `seq` strictly increases per workspace so verification has a stable order
      independent of clock skew.

    SCALE: today the chain is built per-workspace inline via a PG advisory
    lock. At very high write rates, batch entries on a per-workspace Redis
    stream and write the chain async; periodically anchor a checkpoint hash
    to external storage (S3, blockchain, transparency log).
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = uuid_pk()
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Per-workspace monotonic counter (1, 2, 3, …). Filled at insert under
    # an advisory lock so concurrent writers can't get the same number.
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, index=True)

    # Principal that took the action.
    principal_type: Mapped[str] = mapped_column(String(16), nullable=False, default="system")
    principal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    # Retained for backwards compat + a fast index on user actions.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    decision: Mapped[str] = mapped_column(String(16), nullable=False, default="allow")
    # Structured context: query, requested scope, applied filter, deny reason, etc.
    scope: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    prev_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"\x00" * 32)
    entry_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, default=b"\x00" * 32)

    created_at: Mapped[datetime] = created_at_col()
