"""OAuth state management + connector credential storage."""

from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors.base import OAuthTokens
from app.models import Connector, ConnectorCredentials
from app.services.crypto import decrypt, encrypt
from app.services.redis_client import get_redis

_STATE_PREFIX = "oauth:state:"
_STATE_TTL = 300  # seconds


async def issue_state(*, workspace_id: uuid.UUID, user_id: uuid.UUID, provider: str) -> str:
    state = secrets.token_urlsafe(24)
    payload = json.dumps(
        {
            "workspace_id": str(workspace_id),
            "user_id": str(user_id),
            "provider": provider,
            "issued_at": datetime.now(UTC).isoformat(),
        }
    )
    r = get_redis()
    await r.setex(f"{_STATE_PREFIX}{state}", _STATE_TTL, payload)
    return state


async def consume_state(state: str) -> dict | None:
    """Pop-and-return the state payload, or None if missing/expired."""
    r = get_redis()
    key = f"{_STATE_PREFIX}{state}"
    payload = await r.get(key)
    if payload is None:
        return None
    await r.delete(key)  # one-shot
    return json.loads(payload)


def store_credentials(
    *,
    db: Session,
    workspace_id: uuid.UUID,
    connector: Connector,
    tokens: OAuthTokens,
) -> ConnectorCredentials:
    """Persist encrypted tokens for a connector. Replaces any existing row."""
    existing = db.scalar(
        select(ConnectorCredentials).where(
            ConnectorCredentials.workspace_id == workspace_id,
            ConnectorCredentials.connector_id == connector.id,
        )
    )
    access_enc = encrypt(tokens.access_token)
    refresh_enc = encrypt(tokens.refresh_token) if tokens.refresh_token else None

    if existing is None:
        row = ConnectorCredentials(
            workspace_id=workspace_id,
            connector_id=connector.id,
            provider=connector.provider,
            access_token_enc=access_enc,
            refresh_token_enc=refresh_enc,
            expires_at=tokens.expires_at,
            scope=tokens.scope,
        )
        db.add(row)
    else:
        existing.access_token_enc = access_enc
        existing.refresh_token_enc = refresh_enc
        existing.expires_at = tokens.expires_at
        existing.scope = tokens.scope
        existing.provider = connector.provider
        row = existing
    db.flush()
    return row


def load_tokens(
    *,
    db: Session,
    workspace_id: uuid.UUID,
    connector_id: uuid.UUID,
) -> OAuthTokens:
    row = db.scalar(
        select(ConnectorCredentials).where(
            ConnectorCredentials.workspace_id == workspace_id,
            ConnectorCredentials.connector_id == connector_id,
        )
    )
    if row is None:
        raise LookupError("no credentials for connector")
    return OAuthTokens(
        access_token=decrypt(row.access_token_enc),
        refresh_token=decrypt(row.refresh_token_enc) if row.refresh_token_enc else None,
        expires_at=row.expires_at,
        scope=row.scope,
    )


def frontend_callback_url(*, provider: str, status: str, connector_id: uuid.UUID | None = None) -> str:
    base = get_settings().frontend_base.rstrip("/")
    parts = [f"provider={provider}", f"status={status}"]
    if connector_id is not None:
        parts.append(f"connector_id={connector_id}")
    return f"{base}/?view=connectors&" + "&".join(parts)
