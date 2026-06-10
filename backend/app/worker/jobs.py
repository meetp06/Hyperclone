"""Arq job functions.

Each function takes the arq `ctx` dict as first arg. Keep them thin —
push real logic into services so they can be reused outside the queue.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("pioneer.worker")


async def ping(ctx: dict[str, Any], payload: str = "pong") -> dict[str, Any]:
    """Trivial health-check job. Used to verify the queue+worker round trip."""
    log.info("ping job ran, payload=%r", payload)
    return {"ok": True, "echo": payload, "job_id": ctx.get("job_id")}


async def sync_connector(ctx: dict[str, Any], connector_id: str) -> dict[str, Any]:
    """Run the ingestion pipeline for a single connector.

    Implemented in P2.5 — currently a placeholder so WorkerSettings.functions
    can include it from day one.
    """
    from app.services.ingestion import run_sync_connector  # local import: avoid loading fastembed at worker boot

    return await run_sync_connector(connector_id)


async def run_automations(ctx: dict[str, Any], workspace_id: str) -> dict[str, Any]:
    """Generate review-only reply drafts for every enabled automation."""
    from app.automations.runner import run_automations as _run

    return await _run(workspace_id)


async def auto_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
    """Scheduled freshness job (cron). Re-sync every connector that has
    stored credentials so chat always reflects the latest emails / repos /
    pages. Enqueues one sync_connector per connector — they run through the
    same pipeline as a manual "Sync now".

    SCALE: per-tenant schedules + provider webhooks replace this blanket
    poll; today one cron fans out to all connected connectors.
    """
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models import Connector, ConnectorCredentials

    db = SessionLocal()
    try:
        # Only connectors with credentials (real OAuth ones) are syncable.
        cred_ids = {
            r for r in db.scalars(select(ConnectorCredentials.connector_id))
        }
        rows = list(db.scalars(select(Connector)))
        enqueued = 0
        for c in rows:
            if c.id in cred_ids:
                await ctx["redis"].enqueue_job("sync_connector", str(c.id))
                enqueued += 1
        log.info("auto_refresh enqueued %d connector syncs", enqueued)
        return {"ok": True, "enqueued": enqueued}
    finally:
        db.close()
