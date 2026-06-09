import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors import registry as connector_registry
from app.db import get_db
from app.deps import current_user, current_workspace
from app.models import Connector, SyncRun, User, Workspace
from app.repositories.audit import AuditRepo
from app.schemas.connector import (
    ConnectorRead,
    OAuthStartResponse,
    SyncEnqueuedResponse,
    SyncStatusResponse,
)
from app.services import connectors as connector_service
from app.services import oauth as oauth_service
from app.services.queue import get_pool

router = APIRouter(prefix="/connectors", tags=["connectors"])


# ---------- LIST ----------


@router.get("", response_model=list[ConnectorRead])
def list_connectors(
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> list[ConnectorRead]:
    rows = list(
        db.scalars(
            select(Connector)
            .where(Connector.workspace_id == ws.id)
            .order_by(Connector.provider)
        )
    )
    return [ConnectorRead.model_validate(r) for r in rows]


# ---------- LEGACY STUB CONNECT ----------
# Kept for non-OAuth providers in Phase 2 (gdrive/gmail/etc UI tiles still
# call this). Notion now uses the OAuth flow below.


@router.post("/{provider}/connect", response_model=ConnectorRead)
def connect_stub(
    provider: str,
    user: User = Depends(current_user),
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> ConnectorRead:
    provider = provider.lower()
    if connector_registry.has(provider):
        raise HTTPException(
            400,
            f"{provider!r} uses real OAuth — call /connectors/{provider}/oauth/start",
        )
    try:
        c = connector_service.run_connector_sync(
            db=db,
            workspace_id=ws.id,
            actor_user_id=user.id,
            provider=provider,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return ConnectorRead.model_validate(c)


# ---------- OAUTH START ----------


@router.get("/{provider}/oauth/start", response_model=OAuthStartResponse)
async def oauth_start(
    provider: str,
    user: User = Depends(current_user),
    ws: Workspace = Depends(current_workspace),
) -> OAuthStartResponse:
    provider = provider.lower()
    if not connector_registry.has(provider):
        raise HTTPException(404, f"no OAuth connector for {provider!r}")
    connector_impl = connector_registry.get(provider)
    state = await oauth_service.issue_state(
        workspace_id=ws.id, user_id=user.id, provider=provider
    )
    try:
        url = connector_impl.oauth_authorize_url(state)
    except RuntimeError as e:  # missing client id
        raise HTTPException(500, str(e)) from e
    return OAuthStartResponse(authorize_url=url, state=state)


# ---------- OAUTH CALLBACK ----------


@router.get("/{provider}/oauth/callback")
async def oauth_callback(
    provider: str,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    provider = provider.lower()
    settings = get_settings()

    def _fail(reason: str) -> RedirectResponse:
        # Don't echo `code` back through the redirect URL.
        url = oauth_service.frontend_callback_url(provider=provider, status=f"error:{reason}")
        return RedirectResponse(url, status_code=302)

    if error:
        return _fail(error)
    if not code or not state:
        return _fail("missing_code_or_state")
    if not connector_registry.has(provider):
        return _fail("unknown_provider")

    state_payload = await oauth_service.consume_state(state)
    if state_payload is None or state_payload.get("provider") != provider:
        return _fail("invalid_state")

    workspace_id = uuid.UUID(state_payload["workspace_id"])
    user_id = uuid.UUID(state_payload["user_id"])

    connector_impl = connector_registry.get(provider)
    try:
        tokens = await connector_impl.exchange_code(code)
    except Exception:  # noqa: BLE001
        # Intentionally generic — token-exchange errors must not leak to URL.
        return _fail("exchange_failed")

    # Upsert the connectors row.
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
            account_label=(tokens.extra or {}).get("workspace_name") if tokens.extra else None,
        )
        db.add(c)
        db.flush()
    else:
        c.status = "connecting"
        label = (tokens.extra or {}).get("workspace_name") if tokens.extra else None
        if label:
            c.account_label = label

    oauth_service.store_credentials(
        db=db, workspace_id=workspace_id, connector=c, tokens=tokens
    )
    AuditRepo(db).log(
        workspace_id=workspace_id,
        actor_user_id=user_id,
        action="connector.connect",
        resource_type="connector",
        resource_id=c.id,
    )
    db.commit()
    db.refresh(c)

    # Enqueue ingestion. Worker takes it from here.
    pool = await get_pool()
    await pool.enqueue_job("sync_connector", str(c.id))

    return RedirectResponse(
        oauth_service.frontend_callback_url(
            provider=provider, status="connected", connector_id=c.id
        ),
        status_code=302,
    )


# ---------- MANUAL RESYNC ----------


@router.post("/{connector_id}/sync", response_model=SyncEnqueuedResponse)
async def manual_sync(
    connector_id: uuid.UUID,
    user: User = Depends(current_user),
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> SyncEnqueuedResponse:
    c = db.scalar(
        select(Connector).where(Connector.id == connector_id, Connector.workspace_id == ws.id)
    )
    if c is None:
        raise HTTPException(404, "connector not found")
    AuditRepo(db).log(
        workspace_id=ws.id,
        actor_user_id=user.id,
        action="connector.sync.enqueue",
        resource_type="connector",
        resource_id=c.id,
    )
    db.commit()
    pool = await get_pool()
    job = await pool.enqueue_job("sync_connector", str(c.id))
    return SyncEnqueuedResponse(job_id=job.job_id if job else "unknown")


# ---------- LIVE STATUS ----------


@router.get("/{connector_id}/status", response_model=SyncStatusResponse)
def sync_status(
    connector_id: uuid.UUID,
    ws: Workspace = Depends(current_workspace),
    db: Session = Depends(get_db),
) -> SyncStatusResponse:
    c = db.scalar(
        select(Connector).where(Connector.id == connector_id, Connector.workspace_id == ws.id)
    )
    if c is None:
        raise HTTPException(404, "connector not found")

    run = db.scalar(
        select(SyncRun)
        .where(SyncRun.workspace_id == ws.id, SyncRun.connector_id == connector_id)
        .order_by(SyncRun.created_at.desc())
        .limit(1)
    )
    # Synthesize a "queued" state for the post-OAuth window before the
    # worker has picked up the job, so the UI shows progress immediately.
    if run is None and c.status in {"connecting", "syncing"}:
        return SyncStatusResponse(
            connector_id=c.id,
            connector_status=c.status,
            last_synced_at=c.last_synced_at,
            run_id=None,
            run_status="queued",
            docs_seen=0,
            docs_ingested=0,
            chunks_written=0,
            started_at=None,
            finished_at=None,
            error=None,
        )
    return SyncStatusResponse(
        connector_id=c.id,
        connector_status=c.status,
        last_synced_at=c.last_synced_at,
        run_id=run.id if run else None,
        run_status=run.status if run else None,
        docs_seen=run.docs_seen if run else 0,
        docs_ingested=run.docs_ingested if run else 0,
        chunks_written=run.chunks_written if run else 0,
        started_at=run.started_at if run else None,
        finished_at=run.finished_at if run else None,
        error=run.error if run else None,
    )
