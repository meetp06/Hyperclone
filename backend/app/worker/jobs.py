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
