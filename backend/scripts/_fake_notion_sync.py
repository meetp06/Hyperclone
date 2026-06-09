"""Phase-2 ingestion smoke test — runs end-to-end without real Notion creds.

What it does:
  1. Ensure a `notion` Connector row exists for the seeded workspace.
  2. Stash a dummy encrypted access token in `connector_credentials`.
  3. Swap the registry's `notion` entry for a fake provider that yields
     two SourceDocs from memory.
  4. Run the ingestion job directly (no worker needed — exercises the
     same code path the arq worker calls).
  5. Print counts from `documents`, `sync_runs`, and Qdrant.

Re-run to verify idempotency (docs_ingested → 0 on the second pass).
Pass --mutate to change one fake doc's body and confirm chunks turn over.

Run:
    cd backend && uv run python scripts/_fake_notion_sync.py
    cd backend && uv run python scripts/_fake_notion_sync.py --mutate
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from sqlalchemy import select

from app.connectors import registry as connector_registry
from app.connectors.base import Connector, OAuthTokens, SourceDoc
from app.db import SessionLocal
from app.models import Connector as ConnectorModel
from app.models import ConnectorCredentials, Document, SyncRun, Workspace
from app.services.crypto import encrypt
from app.services.ingestion import run_sync_connector


_FAKE_DOCS = [
    SourceDoc(
        external_id="fake-page-1",
        title="Pioneer launch checklist",
        url="https://notion.so/fake/pioneer-launch-checklist",
        text=(
            "Ship Phase 2: OAuth Notion connector, async ingestion via Arq, "
            "chunked embedding into Qdrant with tenant-scoped payloads, "
            "and end-to-end Chat that cites the source page."
        ),
        updated_at=datetime.now(UTC),
    ),
    SourceDoc(
        external_id="fake-page-2",
        title="Customer notes — Acme demo",
        url="https://notion.so/fake/acme-demo",
        text=(
            "Acme ops wants a memory layer that captures Slack threads + "
            "Notion decisions automatically. Strong fit for Pioneer's "
            "connector model. Pricing tier: Team at twenty dollars per seat."
        ),
        updated_at=datetime.now(UTC),
    ),
]


class FakeNotion(Connector):
    provider = "notion"

    def __init__(self, mutate: bool = False) -> None:
        self._mutate = mutate

    def oauth_authorize_url(self, state: str) -> str:
        return f"https://fake.example/auth?state={state}"

    async def exchange_code(self, code: str) -> OAuthTokens:
        return OAuthTokens(access_token="fake-token")

    async def refresh(self, tokens: OAuthTokens) -> OAuthTokens:
        return tokens

    async def list_documents(
        self, tokens: OAuthTokens, cursor: str | None
    ) -> AsyncIterator[tuple[SourceDoc, str | None]]:
        docs = list(_FAKE_DOCS)
        if self._mutate:
            d = docs[0]
            docs[0] = SourceDoc(
                external_id=d.external_id,
                title=d.title + " (revised)",
                url=d.url,
                text=d.text + " UPDATE: launch slipped one week pending review.",
                updated_at=datetime.now(UTC),
            )
        for d in docs:
            yield d, None


def _ensure_connector_and_creds(mutate: bool) -> str:
    db = SessionLocal()
    try:
        ws = db.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
        assert ws is not None, "no workspace — run seed first"

        c = db.scalar(
            select(ConnectorModel).where(
                ConnectorModel.workspace_id == ws.id,
                ConnectorModel.provider == "notion",
            )
        )
        if c is None:
            c = ConnectorModel(
                workspace_id=ws.id,
                provider="notion",
                status="connecting",
                account_label="fake-notion-workspace",
            )
            db.add(c)
            db.flush()

        cred = db.scalar(
            select(ConnectorCredentials).where(
                ConnectorCredentials.workspace_id == ws.id,
                ConnectorCredentials.connector_id == c.id,
            )
        )
        if cred is None:
            cred = ConnectorCredentials(
                workspace_id=ws.id,
                connector_id=c.id,
                provider="notion",
                access_token_enc=encrypt("fake-token"),
            )
            db.add(cred)

        db.commit()
        print(f"workspace={ws.id} connector={c.id} (mutate={mutate})")
        return str(c.id)
    finally:
        db.close()


def _print_state(connector_id: str) -> None:
    db = SessionLocal()
    try:
        cid = connector_id
        from uuid import UUID as _UUID

        docs = db.scalars(
            select(Document).where(Document.connector_id == _UUID(cid))
        ).all()
        runs = db.scalars(
            select(SyncRun)
            .where(SyncRun.connector_id == _UUID(cid))
            .order_by(SyncRun.created_at.desc())
            .limit(3)
        ).all()

        print(f"\n  documents rows: {len(docs)}")
        for d in docs:
            print(f"    {d.external_id} title={d.title!r} hash={d.content_hash[:8]}…")
        print("  sync_runs (latest 3):")
        for r in runs:
            print(
                f"    [{r.status}] docs_seen={r.docs_seen} ingested={r.docs_ingested} "
                f"chunks={r.chunks_written} err={r.error}"
            )

        r2 = httpx.get("http://localhost:6333/collections/pioneer_memories")
        info = r2.json().get("result", {})
        print(f"  qdrant points: {info.get('points_count')}")
    finally:
        db.close()


async def _amain(mutate: bool) -> None:
    cid = _ensure_connector_and_creds(mutate)
    connector_registry._REGISTRY["notion"] = FakeNotion(mutate=mutate)
    result = await run_sync_connector(cid)
    print(f"\nrun_sync_connector returned: {result}")
    _print_state(cid)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mutate", action="store_true")
    args = p.parse_args()
    asyncio.run(_amain(mutate=args.mutate))


if __name__ == "__main__":
    sys.exit(main() or 0)
