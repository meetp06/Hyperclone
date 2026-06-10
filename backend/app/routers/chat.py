"""Grounded chat — retrieval through Phase-3 filter → LLM → SSE stream
with citations + usage metering.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.access import audit_chain
from app.access.policy import allowed_filter
from app.access.principal import Principal, principal_for_request
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.schemas.memory import (
    ChatRequest,
    ChatResponse,
    ChatSource,
    MemoryRead,
    SearchHit,
)
from app.services import memory as memory_service
from app.services import rag
from app.services.llm import LLMUsage
from app.services.rag import _chunk_text_for  # internal helper reuse
from app.services.usage import record_usage

router = APIRouter(prefix="/chat", tags=["chat"])


def _retrieve_and_build_sources(
    db: Session,
    principal: Principal,
    query: str,
    top_k: int,
):
    af = allowed_filter(principal.workspace_id, principal.grants)
    mem_hits = memory_service.search_memory(
        db=db,
        workspace_id=principal.workspace_id,
        principal_type=principal.type,
        principal_id=principal.id,
        access_filter=af,
        query=query,
        top_k=top_k,
    )
    doc_hits = memory_service.search_documents(
        db=db,
        workspace_id=principal.workspace_id,
        principal_type=principal.type,
        principal_id=principal.id,
        access_filter=af,
        query=query,
        top_k=top_k,
    )
    s = get_settings()
    sources = rag.build_sources(
        memories=mem_hits,
        chunks=doc_hits,
        char_budget=s.chat_context_char_budget,
    )
    return mem_hits, doc_hits, sources


def _hits_payload(mem_hits, doc_hits) -> list[SearchHit]:
    s = get_settings()
    out: list[SearchHit] = []
    for h in mem_hits:
        out.append(
            SearchHit(
                kind="memory",
                score=h.score,
                memory=MemoryRead.model_validate(h.memory),
            )
        )
    for c in doc_hits:
        out.append(
            SearchHit(
                kind="document",
                score=c.score,
                document_id=c.document.id,
                document_title=c.document.title,
                document_url=c.document.url,
                document_provider=c.document.provider,
                chunk_index=c.chunk_index,
                chunk_text=_chunk_text_for(c.document.body, c.chunk_index, s)[:600],
            )
        )
    out.sort(key=lambda h: h.score, reverse=True)
    return out


def _source_payload(sources: list[rag.Source]) -> list[ChatSource]:
    return [
        ChatSource(
            cite_id=s.cite_id,
            kind=s.kind,
            id=s.id,
            title=s.title,
            url=s.url,
            collection=s.collection,
            sensitivity=s.sensitivity,
        )
        for s in sources
    ]


def _filter_to_cited(sources: list[rag.Source], answer: str) -> list[rag.Source]:
    cited = rag.extract_cited_ids(answer)
    if not cited:
        return sources
    return [s for s in sources if s.cite_id in cited]


def _sources_as_hits(sources: list[rag.Source]) -> list[SearchHit]:
    """Map resolver Sources to the SearchHit shape for the JSON /chat response."""
    out: list[SearchHit] = []
    for s in sources:
        if s.kind == "memory":
            out.append(SearchHit(kind="memory", score=0.0, memory=None))
        else:
            out.append(
                SearchHit(
                    kind="document", score=0.0,
                    document_id=s.id, document_title=s.title,
                    document_url=s.url, document_provider=s.collection,
                    chunk_index=None, chunk_text=s.snippet[:600],
                )
            )
    return out


def _finalize_audit(
    db: Session,
    principal: Principal,
    *,
    query: str,
    sources: list[rag.Source],
    cited: list[rag.Source],
    usage: LLMUsage,
    provider: str,
    model: str,
    tool_calls: list[str] | None = None,
) -> None:
    """One audit row per chat, recording sources offered + cited + tokens."""
    audit_chain.append(
        db,
        workspace_id=principal.workspace_id,
        principal_type=principal.type,
        principal_id=principal.id,
        action="chat.answer",
        resource_type="chat",
        resource_id=None,
        decision="allow",
        scope={
            "query": query[:280],
            "sources_offered": [s.cite_id for s in sources],
            "sources_cited": [s.cite_id for s in cited],
            "tool_calls": tool_calls or [],
            "tokens_in": usage.input_tokens,
            "tokens_out": usage.output_tokens,
            "provider": provider,
            "model": model,
        },
    )
    record_usage(db, workspace_id=principal.workspace_id, usage=usage)
    db.commit()


# ---------- Non-streaming JSON ----------


@router.post("", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    principal: Principal = Depends(principal_for_request),
    db: Session = Depends(get_db),
) -> ChatResponse:
    from app.services.agent_chat import resolve_chat

    outcome = await resolve_chat(db, principal, req.query, req.top_k)
    cited = _filter_to_cited(outcome.sources, outcome.answer)
    _finalize_audit(
        db, principal,
        query=req.query, sources=outcome.sources, cited=cited,
        usage=outcome.usage, provider=outcome.provider, model=outcome.model,
        tool_calls=outcome.tool_calls,
    )
    return ChatResponse(answer=outcome.answer, hits=_sources_as_hits(outcome.sources))


# ---------- Streaming SSE ----------


def _sse(event: str, data: dict | list) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")


def _word_chunks(text: str, n: int = 5):
    words = text.split(" ")
    for i in range(0, len(words), n):
        yield " ".join(words[i : i + n]) + (" " if i + n < len(words) else "")


@router.post("/stream")
async def chat_stream(
    req: ChatRequest,
    principal: Principal = Depends(principal_for_request),
) -> StreamingResponse:
    """Server-sent events. The agentic resolver runs first (may call tools),
    then the final answer is streamed out as word chunks for UX.

      event: sources  → list of ChatSource the answer drew on
      event: delta    → {text}
      event: usage    → {input_tokens, output_tokens, provider, model}
      event: done     → {cited: [cite_id]}
    """

    async def gen() -> AsyncIterator[bytes]:
        from app.services.agent_chat import resolve_chat

        db = SessionLocal()
        try:
            outcome = await resolve_chat(db, principal, req.query, req.top_k)

            payload = _source_payload(outcome.sources)
            yield _sse("sources", [p.model_dump(mode="json") for p in payload])

            for chunk in _word_chunks(outcome.answer):
                yield _sse("delta", {"text": chunk})

            cited = _filter_to_cited(outcome.sources, outcome.answer)
            yield _sse("usage", {
                "input_tokens": outcome.usage.input_tokens,
                "output_tokens": outcome.usage.output_tokens,
                "provider": outcome.provider,
                "model": outcome.model,
            })
            yield _sse("done", {"cited": [s.cite_id for s in cited]})

            _finalize_audit(
                db, principal,
                query=req.query, sources=outcome.sources, cited=cited,
                usage=outcome.usage, provider=outcome.provider, model=outcome.model,
                tool_calls=outcome.tool_calls,
            )
        finally:
            db.close()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"cache-control": "no-cache", "x-accel-buffering": "no"},
    )
