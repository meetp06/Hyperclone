"""Connector sync jobs.

Phase-1 stub: each provider has a `sync_<provider>` function that the
request handler invokes inline. A queue worker calls the exact same
function later with no other changes.

SCALE: enqueue (workspace_id, connector_id, provider) onto a Redis
stream, have a worker pool consume it. Sync state already lives on the
`connectors` row (status + last_synced_at), so the worker writes there.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Connector
from app.repositories.audit import AuditRepo

import re

_PROVIDER_RE = re.compile(r"^[a-z0-9_-]{2,32}$")


def _stub_sync(provider: str) -> None:
    """Pretend to talk to the provider. Real impls will replace this."""
    _ = provider  # currently a no-op


def run_connector_sync(
    *,
    db: Session,
    workspace_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    provider: str,
) -> Connector:
    """Idempotent connect+sync. Returns the connector row."""
    if not _PROVIDER_RE.match(provider):
        raise ValueError(f"invalid provider id: {provider!r}")

    c = db.scalar(
        select(Connector).where(
            Connector.workspace_id == workspace_id, Connector.provider == provider
        )
    )
    if c is None:
        c = Connector(
            workspace_id=workspace_id,
            provider=provider,
            status="connecting",
            account_label=None,
        )
        db.add(c)
        db.flush()

    c.status = "connecting"
    db.flush()

    _stub_sync(provider)

    c.status = "connected"
    c.account_label = c.account_label or f"{provider}-demo"
    c.last_synced_at = datetime.now(UTC)
    db.flush()

    AuditRepo(db).log(
        workspace_id=workspace_id,
        actor_user_id=actor_user_id,
        action="connector.sync",
        resource_type="connector",
        resource_id=c.id,
    )
    db.commit()
    db.refresh(c)
    return c
