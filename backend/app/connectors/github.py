"""GitHub connector — OAuth App.

Docs:
  https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
  https://docs.github.com/en/rest/repos/contents

Pulls a user's recent repos and ingests every markdown file (README,
docs/, top-level *.md) up to a per-repo cap. Each file is one SourceDoc.

Token semantics: GitHub OAuth-App tokens DO NOT expire by default, so
`refresh` is a no-op (same as Notion).
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

log = logging.getLogger("pioneer.github")

_AUTHORIZE = "https://github.com/login/oauth/authorize"
_TOKEN = "https://github.com/login/oauth/access_token"
_API = "https://api.github.com"
_SCOPES = "repo,read:user"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
_API_VERSION = "2022-11-28"
_MAX_FILE_BYTES = 200_000  # skip huge files


class GitHubConnector(Connector):
    provider = "github"
    default_sensitivity = "internal"
    default_collection = "github"

    def __init__(self) -> None:
        s = get_settings()
        self._client_id = s.github_client_id
        self._client_secret = s.github_client_secret
        self._redirect_uri = s.github_redirect_uri
        self._max_repos = s.github_max_repos
        self._max_files = s.github_max_files_per_repo

    # ---------- OAuth ----------

    def oauth_authorize_url(self, state: str) -> str:
        if not self._client_id:
            raise RuntimeError("GITHUB_CLIENT_ID is not set")
        params = {
            "client_id": self._client_id,
            "redirect_uri": self._redirect_uri,
            "scope": _SCOPES,
            "state": state,
        }
        return f"{_AUTHORIZE}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(
                _TOKEN,
                headers={"Accept": "application/json"},
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": self._redirect_uri,
                },
            )
        if r.status_code != 200:
            raise RuntimeError(f"github oauth exchange failed: HTTP {r.status_code}")
        data = r.json()
        access = data.get("access_token")
        if not access:
            raise RuntimeError(f"github oauth response missing access_token: {data.get('error','?')}")
        return OAuthTokens(
            access_token=access,
            refresh_token=None,
            expires_at=None,
            scope=data.get("scope"),
            extra=None,
        )

    async def refresh(self, tokens: OAuthTokens) -> OAuthTokens:
        # GitHub OAuth-App tokens don't expire by default.
        return tokens

    # ---------- Listing ----------

    async def list_documents(
        self,
        tokens: OAuthTokens,
        cursor: str | None,
    ) -> AsyncIterator[tuple[SourceDoc, str | None]]:
        headers = {
            "Authorization": f"Bearer {tokens.access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": _API_VERSION,
            "User-Agent": "pioneer-connector",
        }
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=headers) as client:
            # 1. List the user's most-recently-updated repos.
            repos = await self._list_repos(client)
            for repo in repos[: self._max_repos]:
                full_name = repo["full_name"]
                default_branch = repo.get("default_branch", "main")
                try:
                    files = await self._find_markdown(client, full_name, default_branch)
                except Exception as e:  # noqa: BLE001
                    log.warning("github: skipping repo %s: %s", full_name, e)
                    continue
                for f in files[: self._max_files]:
                    try:
                        doc = await self._fetch_file(client, full_name, f, default_branch)
                    except Exception as e:  # noqa: BLE001
                        log.warning("github: skipping file %s/%s: %s", full_name, f["path"], e)
                        continue
                    yield doc, None  # repos are paginated server-side; we read top page only

    async def _list_repos(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while len(out) < self._max_repos and page <= 5:
            r = await _backoff(
                client.get,
                f"{_API}/user/repos",
                params={
                    "sort": "updated",
                    "per_page": min(self._max_repos, 100),
                    "page": page,
                    "affiliation": "owner,collaborator",
                },
            )
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            out.extend(batch)
            if len(batch) < 30:
                break
            page += 1
        return out

    async def _find_markdown(
        self, client: httpx.AsyncClient, repo: str, branch: str
    ) -> list[dict[str, Any]]:
        """Top-level + 1 level of subdirs only (cheap + good signal)."""
        items: list[dict[str, Any]] = []

        async def _walk(path: str, depth: int) -> None:
            if depth > 1 or len(items) >= self._max_files:
                return
            r = await _backoff(
                client.get,
                f"{_API}/repos/{repo}/contents/{path}",
                params={"ref": branch},
            )
            entries = r.json()
            if not isinstance(entries, list):
                return
            for e in entries:
                if e["type"] == "file" and e["name"].lower().endswith((".md", ".markdown")):
                    if e.get("size", 0) <= _MAX_FILE_BYTES:
                        items.append(e)
                elif e["type"] == "dir" and depth < 1:
                    # Crawl docs/ + similar; skip noisy node_modules.
                    name = e["name"].lower()
                    if name in {"docs", "documentation", "notes", "specs"}:
                        await _walk(e["path"], depth + 1)

        await _walk("", 0)
        return items

    async def _fetch_file(
        self,
        client: httpx.AsyncClient,
        repo: str,
        meta: dict[str, Any],
        branch: str,
    ) -> SourceDoc:
        r = await _backoff(
            client.get,
            meta.get("url") or f"{_API}/repos/{repo}/contents/{meta['path']}",
        )
        data = r.json()
        content_b64 = data.get("content") or ""
        try:
            text = base64.b64decode(content_b64).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            text = ""
        path = meta["path"]
        return SourceDoc(
            external_id=f"{repo}@{branch}/{path}",
            title=f"{repo}/{path}",
            url=data.get("html_url") or f"https://github.com/{repo}/blob/{branch}/{path}",
            text=text[:60_000],
            updated_at=datetime.now(UTC),  # contents API doesn't carry commit date
        )


# ---------- helpers ----------


async def _backoff(coro, *args, **kwargs) -> httpx.Response:
    """GitHub primary rate limit is 5000 req/hour for authenticated calls.
    Secondary (abuse) limits use 403 + Retry-After. Backoff on 429/403/5xx.
    """
    import asyncio

    delays = [1.0, 3.0, 7.0, 15.0]
    last_resp: httpx.Response | None = None
    for delay in delays:
        r = await coro(*args, **kwargs)
        last_resp = r
        if r.status_code < 400:
            return r
        if r.status_code in (403, 429) or r.status_code >= 500:
            ra = r.headers.get("retry-after")
            sleep_s = float(ra) if ra and ra.replace(".", "", 1).isdigit() else delay
            await asyncio.sleep(sleep_s)
            continue
        r.raise_for_status()
    assert last_resp is not None
    last_resp.raise_for_status()
    return last_resp  # pragma: no cover
