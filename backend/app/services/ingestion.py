"""Per-connector ingestion pipeline.

Called by the arq job `app.worker.jobs.sync_connector`. Reused by tests
and dev scripts so the job stays a one-liner.

Pipeline per document:
    list_documents → hash → dedup → chunk → embed → Qdrant upsert → audit

Idempotency contracts:
- documents UNIQUE(workspace_id, provider, external_id) — re-runs upsert.
- content_hash skip — unchanged docs are not re-embedded.
- Qdrant chunk point ids are deterministic (uuid5 of document_id+chunk_index)
  AND we delete-then-upsert by document_id so updated docs don't orphan
  vectors when chunk count shrinks.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors import registry as connector_registry
from app.connectors.base import SourceDoc
from app.db import SessionLocal
from app.models import Connector, Document, SyncRun
from app.repositories.audit import AuditRepo
from app.services.chunking import chunk_text
from app.services.embeddings import EmbeddingProvider, get_embedder
from app.services.oauth import load_tokens
from app.services.vectorstore import VectorStore, get_vectorstore

log = logging.getLogger("pioneer.ingestion")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


async def run_sync_connector(connector_id_str: str) -> dict[str, Any]:
    """Sync one connector end-to-end. Safe to retry."""
    settings = get_settings()
    connector_id = uuid.UUID(connector_id_str)

    db: Session = SessionLocal()
    run: SyncRun | None = None
    connector: Connector | None = None
    try:
        connector = db.get(Connector, connector_id)
        if connector is None:
            log.warning("sync_connector: no row for %s", connector_id)
            return {"ok": False, "reason": "no_connector"}

        # Guard against concurrent syncs of the same connector. Two
        # parallel sync_connector jobs would race on `connector.last_cursor`
        # and double-bill Notion's rate limit; just skip the dup.
        existing_running = db.scalar(
            select(SyncRun).where(
                SyncRun.connector_id == connector.id,
                SyncRun.status == "running",
            )
        )
        if existing_running is not None:
            log.info(
                "sync_connector: skip — run %s already running for connector %s",
                existing_running.id, connector.id,
            )
            return {"ok": True, "skipped": True, "reason": "already_running"}

        impl = connector_registry.get(connector.provider)

        run = SyncRun(
            workspace_id=connector.workspace_id,
            connector_id=connector.id,
            status="running",
            started_at=_now(),
            cursor=connector.last_cursor,
        )
        db.add(run)
        connector.status = "syncing"
        db.commit()
        db.refresh(run)
        db.refresh(connector)

        tokens = load_tokens(
            db=db, workspace_id=connector.workspace_id, connector_id=connector.id
        )
        tokens = await impl.refresh(tokens)

        embedder = get_embedder()
        vs = get_vectorstore()
        # ensure_collection touches Qdrant — runs in a thread to avoid
        # blocking the worker's event loop on httpx calls inside the client.
        await asyncio.to_thread(vs.ensure_collection, embedder.dim)

        async for source_doc, next_cursor in impl.list_documents(
            tokens, connector.last_cursor
        ):
            await _ingest_one_doc(
                db=db,
                connector=connector,
                run=run,
                source_doc=source_doc,
                embedder=embedder,
                vs=vs,
                settings=settings,
            )
            # Persist cursor + counters per doc so a crash mid-run resumes cleanly.
            connector.last_cursor = next_cursor
            db.commit()

        run.status = "success"
        run.finished_at = _now()
        connector.status = "connected"
        connector.last_synced_at = _now()
        db.commit()

        log.info(
            "sync_connector ok connector=%s docs_seen=%d docs_ingested=%d chunks=%d",
            connector.id, run.docs_seen, run.docs_ingested, run.chunks_written,
        )
        return {
            "ok": True,
            "connector_id": str(connector.id),
            "docs_seen": run.docs_seen,
            "docs_ingested": run.docs_ingested,
            "chunks_written": run.chunks_written,
        }

    except Exception as e:  # noqa: BLE001
        log.exception("sync_connector failed for %s: %s", connector_id, e)
        try:
            if run is not None:
                run.status = "error"
                run.error = str(e)[:512]
                run.finished_at = _now()
            if connector is not None:
                connector.status = "error"
            db.commit()
        except Exception:  # noqa: BLE001
            db.rollback()
        raise
    finally:
        db.close()


async def _ingest_one_doc(
    *,
    db: Session,
    connector: Connector,
    run: SyncRun,
    source_doc: SourceDoc,
    embedder: EmbeddingProvider,
    vs: VectorStore,
    settings,
) -> None:
    run.docs_seen += 1
    workspace_id = connector.workspace_id
    full_text = f"{source_doc.title}\n\n{source_doc.text}"
    content_hash = _hash(full_text)

    existing = db.scalar(
        select(Document).where(
            Document.workspace_id == workspace_id,
            Document.provider == connector.provider,
            Document.external_id == source_doc.external_id,
        )
    )

    if existing is not None and existing.content_hash == content_hash:
        log.debug("skip unchanged doc %s", source_doc.external_id)
        return

    # Phase 3 defaults — every connector's content lands in a collection
    # named after the provider, at sensitivity=internal. Override per
    # connector by adding `default_sensitivity` / `default_collection` on
    # the Connector subclass.
    sensitivity = getattr(
        connector_registry.get(connector.provider), "default_sensitivity", "internal"
    )
    collection = getattr(
        connector_registry.get(connector.provider), "default_collection", connector.provider
    )

    if existing is None:
        doc = Document(
            workspace_id=workspace_id,
            connector_id=connector.id,
            provider=connector.provider,
            external_id=source_doc.external_id,
            title=source_doc.title,
            url=source_doc.url,
            content_hash=content_hash,
            body=full_text,
            sensitivity=sensitivity,
            collection=collection,
            updated_at=source_doc.updated_at,
            ingested_at=_now(),
        )
        db.add(doc)
        db.flush()
    else:
        doc = existing
        doc.title = source_doc.title
        doc.url = source_doc.url
        doc.body = full_text
        doc.content_hash = content_hash
        doc.sensitivity = sensitivity
        doc.collection = collection
        doc.updated_at = source_doc.updated_at
        doc.ingested_at = _now()
        db.flush()

    chunks = list(
        chunk_text(
            full_text,
            target_tokens=settings.chunk_target_tokens,
            overlap_tokens=settings.chunk_overlap_tokens,
        )
    )
    if not chunks:
        log.warning("no chunks for doc %s", source_doc.external_id)
        return

    chunk_texts = [t for _, t in chunks]
    # Embedding is CPU-bound (fastembed onnx) — yield to keep the loop responsive.
    vectors = await asyncio.to_thread(lambda: embedder.embed(chunk_texts))
    indexed_chunks = [(idx, vec) for (idx, _), vec in zip(chunks, vectors, strict=True)]

    # Delete-then-upsert: handles the update case where chunk count shrinks.
    await asyncio.to_thread(
        vs.delete_document_chunks, workspace_id=workspace_id, document_id=doc.id
    )
    await asyncio.to_thread(
        vs.upsert_chunks,
        workspace_id=workspace_id,
        connector_id=connector.id,
        document_id=doc.id,
        chunks=indexed_chunks,
        sensitivity=sensitivity,
        collection=collection,
    )

    AuditRepo(db).log(
        workspace_id=workspace_id,
        actor_user_id=None,  # worker is a system actor; SCALE: per-key principals
        action="document.ingest",
        resource_type="document",
        resource_id=doc.id,
    )

    run.docs_ingested += 1
    run.chunks_written += len(indexed_chunks)
