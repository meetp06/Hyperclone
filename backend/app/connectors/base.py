"""Connector framework.

Implementing a new provider = subclass `Connector`, register it.
No core ingestion logic ever branches on `provider`; the worker calls
`Connector` methods through the registry.

SCALE: nothing here changes when we shard by workspace_id — the
Connector is stateless and gets fresh tokens per job.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class OAuthTokens:
    """Normalized OAuth token bundle. All providers return this shape."""

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    scope: str | None = None
    # Provider-specific extras (e.g. Notion: workspace_id, bot_id, owner).
    extra: dict | None = None


@dataclass(frozen=True)
class SourceDoc:
    """Normalized external document. Provider impls translate to this."""

    external_id: str
    title: str
    url: str | None
    text: str
    updated_at: datetime | None


class Connector(ABC):
    """Abstract base for every provider integration."""

    provider: str = ""

    @abstractmethod
    def oauth_authorize_url(self, state: str) -> str:
        """Return the URL we send the user to for consent."""

    @abstractmethod
    async def exchange_code(self, code: str) -> OAuthTokens:
        """Trade an authorization code for an `OAuthTokens` bundle."""

    @abstractmethod
    async def refresh(self, tokens: OAuthTokens) -> OAuthTokens:
        """Return a fresh token bundle. May return the same object if not needed."""

    @abstractmethod
    def list_documents(
        self,
        tokens: OAuthTokens,
        cursor: str | None,
    ) -> AsyncIterator[tuple[SourceDoc, str | None]]:
        """Async-yield `(doc, next_cursor)` pairs.

        The worker stores each emitted `next_cursor` on the connector
        row after persisting the doc, so an interrupted sync resumes
        without re-pulling completed pages.
        """
