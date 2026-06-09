"""Gmail connector — Google OAuth 2.0.

Docs:
  https://developers.google.com/identity/protocols/oauth2/web-server
  https://developers.google.com/gmail/api/reference/rest/v1/users.messages

Pulls the user's most recent inbox messages (subject + plaintext body)
as `SourceDoc`s. Threads aren't merged — each message is its own document
so they're separately addressable in audit logs.
"""

from __future__ import annotations

import base64
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.connectors.base import Connector, OAuthTokens, SourceDoc

log = logging.getLogger("pioneer.gmail")

_AUTHORIZE = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN = "https://oauth2.googleapis.com/token"
_API = "https://gmail.googleapis.com/gmail/v1"
_SCOPES = "https://www.googleapis.com/auth/gmail.readonly"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class GmailConnector(Connector):
    provider = "gmail"
    # Phase-3 defaults (override per-workspace via the access UI):
    default_sensitivity = "restricted"  # email is sensitive
    default_collection = "gmail"

    def __init__(self) -> None:
        s = get_settings()
        self._client_id = s.gmail_client_id
        self._client_secret = s.gmail_client_secret
        self._redirect_uri = s.gmail_redirect_uri
        self._max_messages = s.gmail_max_messages

    # ---------- OAuth ----------

    def oauth_authorize_url(self, state: str) -> str:
        if not self._client_id:
            raise RuntimeError("GMAIL_CLIENT_ID is not set")
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "access_type": "offline",     # ask Google for a refresh_token
            "prompt": "consent",          # force the consent screen so the
                                          # refresh token actually comes back
            "state": state,
        }
        return f"{_AUTHORIZE}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                _TOKEN,
                data={
                    "code": code,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "redirect_uri": self._redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if r.status_code != 200:
            raise RuntimeError(f"gmail oauth exchange failed: HTTP {r.status_code}")
        data = r.json()
        expires_in = int(data.get("expires_in", 3600))
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in - 60),
            scope=data.get("scope"),
            extra={"id_token": data.get("id_token")},
        )

    async def refresh(self, tokens: OAuthTokens) -> OAuthTokens:
        if not tokens.refresh_token:
            return tokens
        # Refresh only when within 5 minutes of expiry.
        if tokens.expires_at and (tokens.expires_at - datetime.now(UTC)).total_seconds() > 300:
            return tokens
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                _TOKEN,
                data={
                    "refresh_token": tokens.refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                },
            )
        if r.status_code != 200:
            raise RuntimeError(f"gmail refresh failed: HTTP {r.status_code}")
        data = r.json()
        expires_in = int(data.get("expires_in", 3600))
        return OAuthTokens(
            access_token=data["access_token"],
            refresh_token=tokens.refresh_token,
            expires_at=datetime.now(UTC) + timedelta(seconds=expires_in - 60),
            scope=tokens.scope,
            extra=tokens.extra,
        )

    # ---------- Listing ----------

    async def list_documents(
        self,
        tokens: OAuthTokens,
        cursor: str | None,
    ) -> AsyncIterator[tuple[SourceDoc, str | None]]:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            headers={"Authorization": f"Bearer {tokens.access_token}"},
        ) as client:
            params: dict[str, Any] = {
                "maxResults": min(self._max_messages, 100),
                "q": "in:inbox -category:promotions -category:social",
            }
            if cursor:
                params["pageToken"] = cursor

            r = await _backoff(client.get, f"{_API}/users/me/messages", params=params)
            payload = r.json()
            ids = [m["id"] for m in payload.get("messages", []) or []]
            next_cursor = payload.get("nextPageToken")

            for mid in ids:
                try:
                    doc = await self._fetch_message(client, mid)
                except Exception as e:  # noqa: BLE001
                    log.warning("gmail: skipping message %s: %s", mid, e)
                    continue
                yield doc, next_cursor

    async def _fetch_message(self, client: httpx.AsyncClient, mid: str) -> SourceDoc:
        r = await _backoff(
            client.get,
            f"{_API}/users/me/messages/{mid}",
            params={"format": "full"},
        )
        data = r.json()
        headers = {
            h["name"].lower(): h["value"]
            for h in (data.get("payload", {}).get("headers") or [])
        }
        subject = headers.get("subject", "(no subject)")
        from_ = headers.get("from", "")
        date_hdr = headers.get("date", "")
        body = _extract_text(data.get("payload") or {})
        text = f"From: {from_}\nDate: {date_hdr}\nSubject: {subject}\n\n{body}".strip()
        return SourceDoc(
            external_id=mid,
            title=subject[:512],
            url=f"https://mail.google.com/mail/u/0/#inbox/{mid}",
            text=text,
            updated_at=_parse_internal_date(data.get("internalDate")),
        )


# ---------- helpers ----------


def _extract_text(part: dict[str, Any], depth: int = 0) -> str:
    """Recursively pick text/plain (or text/html stripped) from a Gmail
    payload tree. Cap recursion at depth 4 to avoid pathological emails.
    """
    if depth > 4:
        return ""
    mime = part.get("mimeType", "")
    body = part.get("body") or {}
    data = body.get("data")
    chunks: list[str] = []
    if data and mime.startswith("text/"):
        try:
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
            if mime == "text/html":
                decoded = _strip_html(decoded)
            chunks.append(decoded)
        except Exception:  # noqa: BLE001
            pass
    for child in part.get("parts") or []:
        sub = _extract_text(child, depth + 1)
        if sub:
            chunks.append(sub)
    return "\n".join(c.strip() for c in chunks if c.strip())[:32_000]


def _strip_html(html: str) -> str:
    import re

    # very cheap: drop tags, collapse whitespace
    no_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", no_tags)


def _parse_internal_date(ms: str | None) -> datetime | None:
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=UTC)
    except (TypeError, ValueError):
        return None


async def _backoff(coro, *args, **kwargs) -> httpx.Response:
    """Gmail rate-limits ~250 quota units/user/second. Backoff on 429/5xx,
    give up after 4 tries.
    """
    import asyncio

    delays = [0.5, 1.5, 3.5, 7.5]
    last_resp: httpx.Response | None = None
    for delay in delays:
        r = await coro(*args, **kwargs)
        last_resp = r
        if r.status_code < 400:
            return r
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("retry-after")
            sleep_s = float(ra) if ra and ra.replace(".", "", 1).isdigit() else delay
            await asyncio.sleep(sleep_s)
            continue
        r.raise_for_status()
    assert last_resp is not None
    last_resp.raise_for_status()
    return last_resp  # pragma: no cover
