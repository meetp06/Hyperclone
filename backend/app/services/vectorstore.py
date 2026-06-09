"""VectorStore interface + Qdrant default impl.

Every search/upsert is workspace-scoped via payload filtering — this is
the tenant boundary at the vector layer. Two kinds of vectors live in
the same collection, disambiguated by the `source` payload field:

- `source="memory"`     → manual Remember rows (id = memory_id)
- `source="document"`   → connector-ingested chunks (id = uuid5(document_id, chunk_index))

SCALE: Phase-1 uses one collection for all workspaces with payload
filtering. At very large fan-out we'll move to collection-per-shard
keyed by hash(workspace_id) — the interface here doesn't change.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import get_settings


@dataclass(frozen=True)
class MemoryHit:
    memory_id: uuid.UUID
    score: float
    workspace_id: uuid.UUID


@dataclass(frozen=True)
class ChunkHit:
    document_id: uuid.UUID
    chunk_index: int
    score: float
    workspace_id: uuid.UUID
    connector_id: uuid.UUID | None


class VectorStore(ABC):
    @abstractmethod
    def ensure_collection(self, dim: int) -> None: ...

    @abstractmethod
    def upsert_memory(
        self,
        *,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        vector: list[float],
        access_scope: str = "workspace",
        sensitivity: str = "internal",
        collection: str = "manual",
    ) -> None: ...

    @abstractmethod
    def search_memory(
        self,
        *,
        access_filter,  # AccessFilter — kept untyped here to avoid an import cycle
        vector: list[float],
        top_k: int = 5,
    ) -> list[MemoryHit]: ...

    @abstractmethod
    def delete_memory(self, *, workspace_id: uuid.UUID, memory_id: uuid.UUID) -> None: ...

    @abstractmethod
    def upsert_chunks(
        self,
        *,
        workspace_id: uuid.UUID,
        connector_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: list[tuple[int, list[float]]],
        sensitivity: str = "internal",
        collection: str = "notion",
    ) -> None: ...

    @abstractmethod
    def delete_document_chunks(
        self, *, workspace_id: uuid.UUID, document_id: uuid.UUID
    ) -> None: ...

    @abstractmethod
    def search_chunks(
        self,
        *,
        access_filter,
        vector: list[float],
        top_k: int = 5,
    ) -> list[ChunkHit]: ...


# Deterministic namespace for chunk point ids.
_CHUNK_NS = uuid.UUID("3b3bf4d3-7d35-4d8f-bcfb-d6e7b8b3c2d8")


def chunk_point_id(document_id: uuid.UUID, chunk_index: int) -> str:
    """Stable Qdrant point id — re-upserts overwrite instead of duplicate."""
    return str(uuid.uuid5(_CHUNK_NS, f"{document_id}:{chunk_index}"))


class QdrantVectorStore(VectorStore):
    def __init__(self) -> None:
        from qdrant_client import QdrantClient

        settings = get_settings()
        self._collection = settings.qdrant_collection
        self._client = QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            prefer_grpc=False,
        )
        self._ensured_dim: int | None = None
        self._backfilled = False

    # ---------- bootstrap ----------

    def ensure_collection(self, dim: int) -> None:
        from qdrant_client.http import models as qm

        if self._ensured_dim == dim:
            return
        collections = {c.name for c in self._client.get_collections().collections}
        if self._collection not in collections:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=qm.VectorParams(size=dim, distance=qm.Distance.COSINE),
            )
            # Payload indices for fast filtered search.
            for field, schema in [
                ("workspace_id", qm.PayloadSchemaType.KEYWORD),
                ("source", qm.PayloadSchemaType.KEYWORD),
                ("document_id", qm.PayloadSchemaType.KEYWORD),
                ("connector_id", qm.PayloadSchemaType.KEYWORD),
            ]:
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=field,
                    field_schema=schema,
                )
        else:
            info = self._client.get_collection(self._collection)
            existing_dim = info.config.params.vectors.size  # type: ignore[union-attr]
            if existing_dim != dim:
                raise RuntimeError(
                    f"Qdrant collection '{self._collection}' has dim={existing_dim} "
                    f"but embedder produces dim={dim}. Recreate the collection."
                )
            # Best-effort: add missing indices if the collection pre-dates Phase 2.
            try:
                for field in ("source", "document_id", "connector_id"):
                    self._client.create_payload_index(
                        collection_name=self._collection,
                        field_name=field,
                        field_schema=qm.PayloadSchemaType.KEYWORD,
                    )
            except Exception:  # noqa: BLE001
                pass  # already exists is fine
            # Phase-1 points predate the `source` payload field; stamp
            # them as memory so search_memory still finds them.
            if not self._backfilled:
                self._backfill_source_memory()
                self._backfilled = True
        self._ensured_dim = dim

    def _backfill_source_memory(self) -> None:
        """Stamp legacy points (Phase 1/2) with the Phase-3 access fields.

        Older points lack `sensitivity`, `collection`, or `source`. We
        scroll and patch. Idempotent — later runs find every field present
        and update nothing.
        """
        offset = None
        while True:
            points, next_offset = self._client.scroll(
                collection_name=self._collection,
                limit=256,
                with_payload=True,
                offset=offset,
            )
            if not points:
                break

            need_source_memory: list = []
            need_mem_access: list = []
            need_doc_access: list = []
            for p in points:
                payload = p.payload or {}
                src = payload.get("source")
                if src is None:
                    # Pre-Phase-2: assume memory.
                    need_source_memory.append(p.id)
                    src = "memory"
                if "sensitivity" not in payload or "collection" not in payload:
                    if src == "memory":
                        need_mem_access.append(p.id)
                    else:
                        need_doc_access.append(p.id)

            if need_source_memory:
                self._client.set_payload(
                    collection_name=self._collection,
                    payload={"source": "memory"},
                    points=need_source_memory,
                )
            if need_mem_access:
                self._client.set_payload(
                    collection_name=self._collection,
                    payload={"sensitivity": "internal", "collection": "manual"},
                    points=need_mem_access,
                )
            if need_doc_access:
                # Documents in Phase 1/2 are Notion-only; safe to stamp.
                # Future per-connector backfill: join on document_id in PG.
                self._client.set_payload(
                    collection_name=self._collection,
                    payload={"sensitivity": "internal", "collection": "notion"},
                    points=need_doc_access,
                )

            if next_offset is None:
                break
            offset = next_offset

    # ---------- memory (Phase 1, retained) ----------

    def upsert_memory(
        self,
        *,
        workspace_id: uuid.UUID,
        memory_id: uuid.UUID,
        vector: list[float],
        access_scope: str = "workspace",
        sensitivity: str = "internal",
        collection: str = "manual",
    ) -> None:
        from qdrant_client.http import models as qm

        self._client.upsert(
            collection_name=self._collection,
            points=[
                qm.PointStruct(
                    id=str(memory_id),
                    vector=vector,
                    payload={
                        "workspace_id": str(workspace_id),
                        "memory_id": str(memory_id),
                        "access_scope": access_scope,
                        "source": "memory",
                        "sensitivity": sensitivity,
                        "collection": collection,
                    },
                )
            ],
        )

    def _compose_filter(self, access_filter, source_value: str):
        """Workspace + source + AccessFilter merged into a single Qdrant filter."""
        from qdrant_client.http import models as qm

        from app.access.policy import to_qdrant_filter

        af_qf = to_qdrant_filter(access_filter)
        must = list(af_qf.must or [])
        must.append(qm.FieldCondition(key="source", match=qm.MatchValue(value=source_value)))
        return qm.Filter(must=must)

    def search_memory(
        self,
        *,
        access_filter,
        vector: list[float],
        top_k: int = 5,
    ) -> list[MemoryHit]:
        res = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=top_k,
            query_filter=self._compose_filter(access_filter, "memory"),
            with_payload=True,
        ).points
        hits: list[MemoryHit] = []
        for p in res:
            payload = p.payload or {}
            try:
                mid = uuid.UUID(str(payload.get("memory_id")))
                wid = uuid.UUID(str(payload.get("workspace_id")))
            except (TypeError, ValueError):
                continue
            hits.append(MemoryHit(memory_id=mid, score=float(p.score), workspace_id=wid))
        return hits

    def delete_memory(self, *, workspace_id: uuid.UUID, memory_id: uuid.UUID) -> None:
        from qdrant_client.http import models as qm

        # Defense in depth — filter by workspace_id even though id is globally unique.
        self._client.delete(
            collection_name=self._collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="workspace_id",
                            match=qm.MatchValue(value=str(workspace_id)),
                        ),
                        qm.FieldCondition(
                            key="memory_id",
                            match=qm.MatchValue(value=str(memory_id)),
                        ),
                    ]
                )
            ),
        )

    # ---------- chunks (Phase 2) ----------

    def upsert_chunks(
        self,
        *,
        workspace_id: uuid.UUID,
        connector_id: uuid.UUID,
        document_id: uuid.UUID,
        chunks: list[tuple[int, list[float]]],
        sensitivity: str = "internal",
        collection: str = "notion",
    ) -> None:
        from qdrant_client.http import models as qm

        if not chunks:
            return
        points = [
            qm.PointStruct(
                id=chunk_point_id(document_id, idx),
                vector=vec,
                payload={
                    "workspace_id": str(workspace_id),
                    "connector_id": str(connector_id),
                    "document_id": str(document_id),
                    "chunk_index": idx,
                    "source": "document",
                    "sensitivity": sensitivity,
                    "collection": collection,
                },
            )
            for idx, vec in chunks
        ]
        self._client.upsert(collection_name=self._collection, points=points)

    def delete_document_chunks(
        self, *, workspace_id: uuid.UUID, document_id: uuid.UUID
    ) -> None:
        from qdrant_client.http import models as qm

        self._client.delete(
            collection_name=self._collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="workspace_id",
                            match=qm.MatchValue(value=str(workspace_id)),
                        ),
                        qm.FieldCondition(
                            key="document_id",
                            match=qm.MatchValue(value=str(document_id)),
                        ),
                    ]
                )
            ),
        )

    def search_chunks(
        self,
        *,
        access_filter,
        vector: list[float],
        top_k: int = 5,
    ) -> list[ChunkHit]:
        res = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=top_k,
            query_filter=self._compose_filter(access_filter, "document"),
            with_payload=True,
        ).points
        hits: list[ChunkHit] = []
        for p in res:
            payload = p.payload or {}
            try:
                did = uuid.UUID(str(payload.get("document_id")))
                wid = uuid.UUID(str(payload.get("workspace_id")))
            except (TypeError, ValueError):
                continue
            cid_raw = payload.get("connector_id")
            try:
                cid = uuid.UUID(str(cid_raw)) if cid_raw else None
            except (TypeError, ValueError):
                cid = None
            idx = payload.get("chunk_index")
            if not isinstance(idx, int):
                continue
            hits.append(
                ChunkHit(
                    document_id=did,
                    chunk_index=idx,
                    score=float(p.score),
                    workspace_id=wid,
                    connector_id=cid,
                )
            )
        return hits


_default: VectorStore | None = None


def get_vectorstore() -> VectorStore:
    global _default
    if _default is None:
        _default = QdrantVectorStore()
    return _default
