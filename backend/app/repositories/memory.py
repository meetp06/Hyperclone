import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Memory


class MemoryRepo:
    """Tenant-scoped data access for memories.

    Every method takes workspace_id and applies it to every query. This is
    the application-layer tenant boundary; the row also carries workspace_id
    so DB-level RLS / sharding can be enforced later.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def create(
        self,
        *,
        workspace_id: uuid.UUID,
        author_user_id: uuid.UUID | None,
        title: str,
        body: str,
        source: str = "manual",
    ) -> Memory:
        m = Memory(
            workspace_id=workspace_id,
            author_user_id=author_user_id,
            title=title,
            body=body,
            source=source,
        )
        self.db.add(m)
        self.db.flush()
        return m

    def list_recent(
        self, *, workspace_id: uuid.UUID, limit: int = 100
    ) -> list[Memory]:
        stmt = (
            select(Memory)
            .where(Memory.workspace_id == workspace_id)
            .order_by(Memory.created_at.desc())
            .limit(limit)
        )
        return list(self.db.scalars(stmt))

    def get_many(
        self, *, workspace_id: uuid.UUID, ids: list[uuid.UUID]
    ) -> list[Memory]:
        if not ids:
            return []
        stmt = select(Memory).where(
            Memory.workspace_id == workspace_id, Memory.id.in_(ids)
        )
        return list(self.db.scalars(stmt))
