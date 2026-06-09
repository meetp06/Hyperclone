import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models._base import created_at_col, uuid_pk


class ConnectorCredentials(Base):
    """Encrypted OAuth tokens for a single (workspace, connector).

    Tokens stay tenant-scoped: workspace_id is part of every query.
    Plaintext tokens never live in the row — `crypto.encrypt` happens
    before persisting and `crypto.decrypt` only when a worker fetches them.

    SCALE: move ciphertext to a KMS-backed secrets manager and store
    only a key reference here. Then a stolen DB dump yields no tokens.
    """

    __tablename__ = "connector_credentials"
    __table_args__ = (
        UniqueConstraint("workspace_id", "connector_id", name="uq_creds_workspace_connector"),
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
    access_token_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    refresh_token_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = created_at_col()
