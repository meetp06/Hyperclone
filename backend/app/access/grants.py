"""Grant CRUD + load-to-GrantSet helpers."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access.policy import GrantSet, WILDCARD
from app.models import AccessGrant


def load_grant(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID,
) -> GrantSet:
    """Return the principal's compiled GrantSet. Empty (deny-by-default)
    if no row exists.
    """
    row = db.scalar(
        select(AccessGrant).where(
            AccessGrant.workspace_id == workspace_id,
            AccessGrant.principal_type == principal_type,
            AccessGrant.principal_id == principal_id,
        )
    )
    if row is None:
        return GrantSet()  # deny everything
    return GrantSet(
        sensitivity_max=row.sensitivity_max,
        collections=frozenset(row.collections or []),
        actions=frozenset(row.actions or []),
    )


def upsert_grant(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID,
    sensitivity_max: int,
    collections: list[str],
    actions: list[str],
    created_by: uuid.UUID | None = None,
) -> AccessGrant:
    row = db.scalar(
        select(AccessGrant).where(
            AccessGrant.workspace_id == workspace_id,
            AccessGrant.principal_type == principal_type,
            AccessGrant.principal_id == principal_id,
        )
    )
    if row is None:
        row = AccessGrant(
            workspace_id=workspace_id,
            principal_type=principal_type,
            principal_id=principal_id,
            sensitivity_max=sensitivity_max,
            collections=list(collections),
            actions=list(actions),
            created_by=created_by,
        )
        db.add(row)
    else:
        row.sensitivity_max = sensitivity_max
        row.collections = list(collections)
        row.actions = list(actions)
        if created_by:
            row.created_by = created_by
    db.flush()
    return row


def revoke_grant(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID,
) -> None:
    row = db.scalar(
        select(AccessGrant).where(
            AccessGrant.workspace_id == workspace_id,
            AccessGrant.principal_type == principal_type,
            AccessGrant.principal_id == principal_id,
        )
    )
    if row is not None:
        db.delete(row)
        db.flush()


WILDCARD_GRANT = ("read", "write")


def default_user_grant_kwargs(workspace_id: uuid.UUID, user_id: uuid.UUID) -> dict:
    """The grant we install for a fresh user → full workspace access.

    Agents do NOT get a default — that's the deny-by-default contract.
    """
    return dict(
        workspace_id=workspace_id,
        principal_type="user",
        principal_id=user_id,
        sensitivity_max=2,  # restricted
        collections=[WILDCARD],
        actions=list(WILDCARD_GRANT),
    )
