"""Agentic chat resolver — RAG context + tool-calling for exact answers.

Flow:
  1. Retrieve access-controlled semantic context (memories + doc chunks).
  2. Hand the model the context AND tools (count_documents, list_recent).
  3. The model answers from context for normal questions, or calls a tool
     for counting / recency / date-filtered questions, then answers exactly.
  4. Providers without tool support (stub, plain anthropic) fall back to a
     single context-only completion.

Access control is preserved end to end: tools query Postgres through the
same AccessFilter the vector search uses.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.access.policy import allowed_filter
from app.access.principal import Principal
from app.config import get_settings
from app.services import memory as memory_service
from app.services import rag
from app.services.agent_tools import TOOL_SCHEMAS, execute_tool
from app.services.llm import LLMProvider, LLMUsage, get_llm

_MAX_TOOL_ROUNDS = 3


@dataclass
class ChatOutcome:
    answer: str
    sources: list[rag.Source]
    usage: LLMUsage
    provider: str
    model: str
    tool_calls: list[str] = field(default_factory=list)


def _tools_system_prompt() -> str:
    today = datetime.now(UTC).strftime("%Y-%m-%d (%A)")
    return (
        rag.SYSTEM_PROMPT
        + "\n\n"
        + f"Today's date is {today}.\n"
        + "You ALSO have tools for facts the context can't give you:\n"
        + "- count_documents: counts emails/files/pages, optionally by collection, "
        + "recent N days, or title substring. Use for 'how many ... today/this month'.\n"
        + "- list_recent_documents: newest items by date. Use for 'my last email', "
        + "'latest github repo/project', 'most recent ...'.\n"
        + "Collections: gmail (emails), github (repo files/READMEs), notion (pages), manual (saved notes).\n"
        + "Mapping: 'email(s)' → collection='gmail'; 'repo/project/code/file' → collection='github'; "
        + "'page/doc/note' → collection='notion'. Always set the matching collection.\n"
        + "Tool argument types are strict: limit and since_days must be plain integers (e.g. 1, not \"1\").\n"
        + "When a question is about a COUNT or the LATEST/MOST-RECENT item, CALL THE TOOL "
        + "instead of guessing from context. After a tool returns, answer exactly from its result."
    )


def _retrieve(db: Session, principal: Principal, query: str, top_k: int):
    af = allowed_filter(principal.workspace_id, principal.grants)
    mem = memory_service.search_memory(
        db=db, workspace_id=principal.workspace_id,
        principal_type=principal.type, principal_id=principal.id,
        access_filter=af, query=query, top_k=top_k,
    )
    docs = memory_service.search_documents(
        db=db, workspace_id=principal.workspace_id,
        principal_type=principal.type, principal_id=principal.id,
        access_filter=af, query=query, top_k=top_k,
    )
    s = get_settings()
    sources = rag.build_sources(memories=mem, chunks=docs, char_budget=s.chat_context_char_budget)
    return af, sources


async def resolve_chat(
    db: Session, principal: Principal, query: str, top_k: int,
    llm: LLMProvider | None = None,
) -> ChatOutcome:
    llm = llm or get_llm()
    af, sources = _retrieve(db, principal, query, top_k)

    # No tools available → single context-only completion (legacy path).
    if not getattr(llm, "supports_tools", False):
        messages = rag.build_messages(query, sources)
        result = await llm.complete(messages)
        return ChatOutcome(
            answer=result.text, sources=sources, usage=result.usage,
            provider=llm.name, model=llm.model,
        )

    # Agentic path: context + tools. Any tool-call failure (e.g. a model
    # that emits malformed args) degrades to a plain context answer — the
    # endpoint must never 500 over a flaky tool call.
    try:
        return await _agentic_loop(db, principal, query, sources, af, llm)
    except Exception:  # noqa: BLE001
        messages = rag.build_messages(query, sources)
        result = await llm.complete(messages)
        return ChatOutcome(
            answer=result.text, sources=sources, usage=result.usage,
            provider=llm.name, model=llm.model,
        )


async def _agentic_loop(db, principal, query, sources, af, llm) -> ChatOutcome:
    base = rag.build_messages(query, sources)
    messages: list[dict] = [
        {"role": "system", "content": _tools_system_prompt()},
        {"role": "user", "content": base[1].content},
    ]

    total = LLMUsage()
    used_tools: list[str] = []
    tool_sources: list[rag.Source] = []

    for round_i in range(_MAX_TOOL_ROUNDS):
        last_round = round_i == _MAX_TOOL_ROUNDS - 1
        turn = await llm.complete_with_tools(
            messages,
            tools=[] if last_round else TOOL_SCHEMAS,
            tool_choice="auto",
        )
        total = LLMUsage(total.input_tokens + turn.usage.input_tokens,
                         total.output_tokens + turn.usage.output_tokens)

        if not turn.tool_calls:
            answer = turn.text or "I don't have that in the workspace yet."
            return ChatOutcome(
                answer=answer,
                sources=_merge_sources(sources, tool_sources),
                usage=total, provider=llm.name, model=llm.model,
                tool_calls=used_tools,
            )

        # Append the assistant tool-call message, then run each tool.
        if turn.raw_assistant:
            messages.append(turn.raw_assistant)
        for tc in turn.tool_calls:
            used_tools.append(tc.name)
            result = execute_tool(db, af, tc.name, tc.arguments)
            tool_sources.extend(_sources_from_tool(result))
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, default=str),
            })

    # Exhausted rounds without a final text — synthesize one more plain call.
    final = await llm.complete_with_tools(messages, tools=[], tool_choice="auto")
    total = LLMUsage(total.input_tokens + final.usage.input_tokens,
                     total.output_tokens + final.usage.output_tokens)
    return ChatOutcome(
        answer=final.text or "I don't have that in the workspace yet.",
        sources=_merge_sources(sources, tool_sources),
        usage=total, provider=llm.name, model=llm.model, tool_calls=used_tools,
    )


def _sources_from_tool(result: dict) -> list[rag.Source]:
    """Turn list_recent_documents items into citable Sources for the UI."""
    out: list[rag.Source] = []
    for item in (result or {}).get("items", []) or []:
        did = item.get("document_id")
        if not did:
            continue
        try:
            uid = uuid.UUID(did)
        except (TypeError, ValueError):
            continue
        out.append(rag.Source(
            kind="document", id=uid, title=item.get("title") or "(untitled)",
            url=item.get("url"), snippet="", collection=item.get("collection") or "",
            sensitivity="internal", cite_id=f"doc:{uid}", date=item.get("date"),
        ))
    return out


def _merge_sources(a: list[rag.Source], b: list[rag.Source]) -> list[rag.Source]:
    seen: set[str] = set()
    out: list[rag.Source] = []
    for s in [*b, *a]:  # tool-surfaced (recency) first
        if s.cite_id in seen:
            continue
        seen.add(s.cite_id)
        out.append(s)
    return out
