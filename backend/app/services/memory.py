"""Memory service: orchestrates Postgres + vector store + audit log.

Single place where ingestion + retrieval cross all three subsystems.
Every write produces an audit_log row; every search produces one too.

SCALE: embedding + upsert happen inline. Wrap `write_memory` as a
queue job (Redis stream → worker) to make ingestion async; signature
stays identical because services already take all inputs as args.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import audit_chain
from app.access.policy import AccessFilter, allowed_filter
from app.models import Document, Memory
from app.repositories.memory import MemoryRepo
from app.services.embeddings import EmbeddingProvider, get_embedder
from app.services.vectorstore import VectorStore, get_vectorstore


@dataclass
class SearchResult:
    memory: Memory
    score: float


@dataclass
class ChunkResult:
    """A chunk hit from an ingested document."""

    document: Document
    chunk_index: int
    score: float


def write_memory(
    *,
    db: Session,
    workspace_id: uuid.UUID,
    author_user_id: uuid.UUID | None,
    principal_type: str,
    principal_id: uuid.UUID | None,
    title: str,
    body: str,
    source: str = "manual",
    sensitivity: str = "internal",
    collection: str = "manual",
    embedder: EmbeddingProvider | None = None,
    vectorstore: VectorStore | None = None,
) -> Memory:
    embedder = embedder or get_embedder()
    vs = vectorstore or get_vectorstore()
    vs.ensure_collection(embedder.dim)

    repo = MemoryRepo(db)

    m = repo.create(
        workspace_id=workspace_id,
        author_user_id=author_user_id,
        title=title,
        body=body,
        source=source,
    )
    # Stamp access fields on the PG row.
    m.sensitivity = sensitivity
    m.collection = collection
    db.flush()

    [vec] = embedder.embed([f"{title}\n\n{body}"])
    vs.upsert_memory(
        workspace_id=workspace_id,
        memory_id=m.id,
        vector=vec,
        sensitivity=sensitivity,
        collection=collection,
    )

    audit_chain.append(
        db,
        workspace_id=workspace_id,
        principal_type=principal_type,
        principal_id=principal_id,
        action="memory.write",
        resource_type="memory",
        resource_id=m.id,
        decision="allow",
        scope={"sensitivity": sensitivity, "collection": collection},
    )

    db.commit()
    db.refresh(m)
    return m


def search_memory(
    *,
    db: Session,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID | None,
    access_filter: AccessFilter,
    query: str,
    top_k: int = 5,
    embedder: EmbeddingProvider | None = None,
    vectorstore: VectorStore | None = None,
) -> list[SearchResult]:
    embedder = embedder or get_embedder()
    vs = vectorstore or get_vectorstore()
    vs.ensure_collection(embedder.dim)

    [qvec] = embedder.embed([query])

    # Deny-by-default short-circuit so we never hit Qdrant when the
    # principal can't read anything — the API still records the attempt.
    if not access_filter.allows_any_read:
        audit_chain.append(
            db,
            workspace_id=workspace_id,
            principal_type=principal_type,
            principal_id=principal_id,
            action="memory.search",
            resource_type="memory",
            decision="allow",
            scope={
                "query": query,
                "result": "empty",
                "reason": "no_read_grant",
                "filter": _af_summary(access_filter),
            },
        )
        db.commit()
        return []

    hits = vs.search_memory(access_filter=access_filter, vector=qvec, top_k=top_k)

    repo = MemoryRepo(db)
    rows = {
        m.id: m
        for m in repo.get_many(workspace_id=workspace_id, ids=[h.memory_id for h in hits])
    }

    audit_chain.append(
        db,
        workspace_id=workspace_id,
        principal_type=principal_type,
        principal_id=principal_id,
        action="memory.search",
        resource_type="memory",
        decision="allow",
        scope={
            "query": query,
            "hits": len(hits),
            "top_k": top_k,
            "filter": _af_summary(access_filter),
        },
    )
    db.commit()

    results: list[SearchResult] = []
    for h in hits:
        m = rows.get(h.memory_id)
        if m is not None:
            results.append(SearchResult(memory=m, score=h.score))
    return results


def _af_summary(af: AccessFilter) -> dict:
    """Tiny JSON-safe snapshot for the audit row's `scope` field."""
    return {
        "workspace_id": str(af.workspace_id),
        "sensitivity_max": af.sensitivity_max,
        "collections": sorted(af.collections),
        "wildcard": af.wildcard,
    }


def search_documents(
    *,
    db: Session,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID | None,
    access_filter: AccessFilter,
    query: str,
    top_k: int = 5,
    embedder: EmbeddingProvider | None = None,
    vectorstore: VectorStore | None = None,
) -> list[ChunkResult]:
    """Semantic search across ingested connector documents (chunks)."""
    embedder = embedder or get_embedder()
    vs = vectorstore or get_vectorstore()
    vs.ensure_collection(embedder.dim)

    [qvec] = embedder.embed([query])

    if not access_filter.allows_any_read:
        audit_chain.append(
            db,
            workspace_id=workspace_id,
            principal_type=principal_type,
            principal_id=principal_id,
            action="document.search",
            resource_type="document",
            decision="allow",
            scope={
                "query": query,
                "result": "empty",
                "reason": "no_read_grant",
                "filter": _af_summary(access_filter),
            },
        )
        db.commit()
        return []

    hits = vs.search_chunks(access_filter=access_filter, vector=qvec, top_k=top_k)

    doc_ids = list({h.document_id for h in hits})
    rows = (
        list(
            db.scalars(
                select(Document).where(
                    Document.workspace_id == workspace_id,
                    Document.id.in_(doc_ids),
                )
            )
        )
        if doc_ids
        else []
    )
    by_id = {d.id: d for d in rows}

    audit_chain.append(
        db,
        workspace_id=workspace_id,
        principal_type=principal_type,
        principal_id=principal_id,
        action="document.search",
        resource_type="document",
        decision="allow",
        scope={
            "query": query,
            "hits": len(hits),
            "top_k": top_k,
            "filter": _af_summary(access_filter),
        },
    )
    db.commit()

    out: list[ChunkResult] = []
    for h in hits:
        doc = by_id.get(h.document_id)
        if doc is None:
            continue
        out.append(ChunkResult(document=doc, chunk_index=h.chunk_index, score=h.score))
    return out


def list_recent(
    *,
    db: Session,
    workspace_id: uuid.UUID,
    principal_type: str,
    principal_id: uuid.UUID | None,
    access_filter: AccessFilter,
    limit: int = 100,
) -> list[Memory]:
    """List recent memories the principal is allowed to see.

    PG-side filter is the policy's mirror — we strip rows the access
    filter would reject from the vector store. Keeps the UI consistent.
    """
    repo = MemoryRepo(db)
    rows = repo.list_recent(workspace_id=workspace_id, limit=limit)

    if access_filter.allows_any_read:
        from app.access.policy import SENSITIVITY_RANK, allowed_sensitivities

        allowed_levels = set(allowed_sensitivities(access_filter))
        wildcard = access_filter.wildcard
        allowed_cols = access_filter.collections
        rows = [
            m for m in rows
            if (m.sensitivity in allowed_levels)
            and (wildcard or m.collection in allowed_cols)
        ]
    else:
        rows = []

    audit_chain.append(
        db,
        workspace_id=workspace_id,
        principal_type=principal_type,
        principal_id=principal_id,
        action="memory.list",
        resource_type="memory",
        decision="allow",
        scope={"hits": len(rows), "filter": _af_summary(access_filter)},
    )
    db.commit()
    return rows
