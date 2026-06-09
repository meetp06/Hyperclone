"""Notion connector.

Uses the public OAuth flow + the Notion REST API. Notion access tokens
are long-lived bearer tokens (no refresh), so `refresh` is a no-op.

Docs:
  https://developers.notion.com/docs/authorization
  https://developers.notion.com/reference/post-search
  https://developers.notion.com/reference/get-block-children
"""

from __future__ import annotations

import base64
import logging
from collections.abc import AsyncIterator
from datetime import datetime, UTC
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.connectors.base import Connector, OAuthTokens, SourceDoc

log = logging.getLogger("pioneer.notion")

NOTION_VERSION = "2022-06-28"
_DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_MAX_BLOCK_DEPTH = 3


class NotionConnector(Connector):
    provider = "notion"

    def __init__(self) -> None:
        s = get_settings()
        self._client_id = s.notion_client_id
        self._client_secret = s.notion_client_secret
        self._redirect_uri = s.notion_redirect_uri
        self._api_base = s.notion_api_base
        self._auth_url = s.notion_oauth_authorize
        self._token_url = s.notion_oauth_token

    # ---------- OAuth ----------

    def oauth_authorize_url(self, state: str) -> str:
        if not self._client_id:
            raise RuntimeError("NOTION_CLIENT_ID is not set")
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "owner": "user",
            "redirect_uri": self._redirect_uri,
            "state": state,
        }
        return f"{self._auth_url}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        basic = base64.b64encode(
            f"{self._client_id}:{self._client_secret}".encode()
        ).decode()
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
            r = await client.post(
                self._token_url,
                headers={
                    "Authorization": f"Basic {basic}",
                    "Content-Type": "application/json",
                    "Notion-Version": NOTION_VERSION,
                },
                json={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                },
            )
        if r.status_code != 200:
            # Don't log the response body — it can echo back the secret.
            raise RuntimeError(f"notion oauth exchange failed: HTTP {r.status_code}")
        data = r.json()
        access = data.get("access_token")
        if not access:
            raise RuntimeError("notion oauth response missing access_token")
        return OAuthTokens(
            access_token=access,
            refresh_token=None,  # Notion does not issue refresh tokens.
            expires_at=None,
            scope=None,
            extra={
                "workspace_id": data.get("workspace_id"),
                "workspace_name": data.get("workspace_name"),
                "bot_id": data.get("bot_id"),
                "owner": data.get("owner"),
            },
        )

    async def refresh(self, tokens: OAuthTokens) -> OAuthTokens:
        # Notion tokens don't expire. SCALE: when adding a provider that
        # does (Google), branch here on `provider` is the wrong shape —
        # each Connector handles its own refresh.
        return tokens

    # ---------- Listing ----------

    async def list_documents(
        self,
        tokens: OAuthTokens,
        cursor: str | None,
    ) -> AsyncIterator[tuple[SourceDoc, str | None]]:
        async with httpx.AsyncClient(
            timeout=_DEFAULT_TIMEOUT,
            headers={
                "Authorization": f"Bearer {tokens.access_token}",
                "Notion-Version": NOTION_VERSION,
                "Content-Type": "application/json",
            },
        ) as client:
            start_cursor: str | None = cursor
            while True:
                body: dict[str, Any] = {
                    "page_size": 50,
                    "filter": {"property": "object", "value": "page"},
                }
                if start_cursor:
                    body["start_cursor"] = start_cursor

                r = await _retry_post(client, f"{self._api_base}/search", body)
                payload = r.json()
                results = payload.get("results", []) or []
                next_cursor = payload.get("next_cursor")
                has_more = bool(payload.get("has_more"))

                for page in results:
                    if page.get("object") != "page":
                        continue
                    try:
                        doc = await self._page_to_doc(client, page)
                    except Exception as e:  # noqa: BLE001
                        log.warning("notion: skipping page %s: %s", page.get("id"), e)
                        continue
                    yield doc, next_cursor

                if not has_more or not next_cursor:
                    break
                start_cursor = next_cursor

    # ---------- internals ----------

    async def _page_to_doc(
        self, client: httpx.AsyncClient, page: dict[str, Any]
    ) -> SourceDoc:
        page_id = page["id"]
        title = _extract_page_title(page) or "(untitled)"
        url = page.get("url")
        updated_iso = page.get("last_edited_time")
        updated_at = _parse_iso(updated_iso)
        text = await self._fetch_block_text(client, page_id, depth=0)
        return SourceDoc(
            external_id=page_id,
            title=title,
            url=url,
            text=text or title,  # never empty — preserves embeddability
            updated_at=updated_at,
        )

    async def _fetch_block_text(
        self, client: httpx.AsyncClient, block_id: str, depth: int
    ) -> str:
        if depth > _MAX_BLOCK_DEPTH:
            return ""
        chunks: list[str] = []
        start_cursor: str | None = None
        while True:
            params = {"page_size": 100}
            if start_cursor:
                params["start_cursor"] = start_cursor
            r = await _retry_get(
                client, f"{self._api_base}/blocks/{block_id}/children", params
            )
            data = r.json()
            for block in data.get("results", []) or []:
                txt = _block_text(block)
                if txt:
                    chunks.append(txt)
                if block.get("has_children") and depth < _MAX_BLOCK_DEPTH:
                    child_txt = await self._fetch_block_text(
                        client, block["id"], depth + 1
                    )
                    if child_txt:
                        chunks.append(child_txt)
            if not data.get("has_more"):
                break
            start_cursor = data.get("next_cursor")
            if not start_cursor:
                break
        return "\n".join(c for c in chunks if c)


# ---------- helpers ----------


def _extract_page_title(page: dict[str, Any]) -> str | None:
    """Pull the title plaintext from the page's properties."""
    props = page.get("properties") or {}
    for v in props.values():
        if v.get("type") == "title":
            arr = v.get("title") or []
            return _rich_text_to_plain(arr)
    return None


def _rich_text_to_plain(rich: list[dict[str, Any]]) -> str:
    return "".join((t.get("plain_text") or "") for t in rich)


_TEXT_BLOCK_TYPES = {
    "paragraph", "heading_1", "heading_2", "heading_3",
    "bulleted_list_item", "numbered_list_item", "to_do",
    "toggle", "callout", "quote", "code",
}


def _block_text(block: dict[str, Any]) -> str:
    t = block.get("type")
    if not t:
        return ""
    if t in _TEXT_BLOCK_TYPES:
        rich = (block.get(t) or {}).get("rich_text") or []
        return _rich_text_to_plain(rich)
    if t == "child_page":
        return (block.get("child_page") or {}).get("title") or ""
    return ""


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


async def _retry_post(client: httpx.AsyncClient, url: str, json: dict) -> httpx.Response:
    return await _with_backoff(lambda: client.post(url, json=json))


async def _retry_get(client: httpx.AsyncClient, url: str, params: dict) -> httpx.Response:
    return await _with_backoff(lambda: client.get(url, params=params))


async def _with_backoff(coro_factory) -> httpx.Response:
    """Notion rate-limits ~3 rps. Backoff on 429/5xx, give up after 4 tries.

    SCALE: today we wait inline on the worker; in a high-fanout deployment,
    push the rate-limit token bucket out to Redis so all workers cooperate.
    """
    import asyncio

    delays = [0.5, 1.5, 3.5, 7.5]
    last_resp: httpx.Response | None = None
    for delay in delays:
        r = await coro_factory()
        last_resp = r
        if r.status_code < 400:
            return r
        if r.status_code == 429 or r.status_code >= 500:
            ra = r.headers.get("retry-after")
            sleep_s = float(ra) if ra and ra.replace(".", "", 1).isdigit() else delay
            await asyncio.sleep(sleep_s)
            continue
        # Hard 4xx — surface without retry; caller decides.
        r.raise_for_status()
    assert last_resp is not None
    last_resp.raise_for_status()
    return last_resp  # pragma: no cover
