"""Agentic tools for chat — exact answers RAG can't give.

Pure semantic search can't count, can't sort by recency, can't filter by
date. These tools query Postgres directly (access-controlled) so the LLM
can answer "how many emails this month", "my last github repo", etc.

Every tool respects the caller's Phase-3 AccessFilter — collection +
sensitivity gates apply identically to tool queries and vector search.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.access.policy import AccessFilter, allowed_sensitivities
from app.models import Document

# OpenAI / Groq tool schemas.
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "count_documents",
            "description": (
                "Count ingested items in the workspace. ALWAYS set collection to "
                "match the question: 'emails'→gmail, 'repos/files/code'→github, "
                "'pages/notes'→notion. Use for 'how many emails today', "
                "'how many job emails this month', 'how many notion pages'. "
                "Optionally add a recent time window or title substring."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {
                        "type": "string",
                        "enum": ["gmail", "github", "notion"],
                        "description": "limit to one source",
                    },
                    "since_days": {
                        "type": ["integer", "string"],
                        "description": "only items from the last N days. today=1, this week=7, this month=31",
                    },
                    "title_contains": {
                        "type": "string",
                        "description": "case-insensitive substring the title must contain, e.g. 'job', 'invoice'",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_recent_documents",
            "description": (
                "List the most recent items by date (newest first). Use for "
                "'my last email', 'latest github repo/project', 'recent files', "
                "'what did I get most recently'. Returns title, date, url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "collection": {
                        "type": "string",
                        "enum": ["gmail", "github", "notion"],
                    },
                    "limit": {"type": ["integer", "string"], "description": "how many (max 25)"},
                    "title_contains": {
                        "type": "string",
                        "description": "case-insensitive substring filter on title",
                    },
                },
                "required": [],
            },
        },
    },
]


def _doc_conditions(af: AccessFilter) -> list:
    """Translate an AccessFilter into SQLAlchemy WHERE conditions on Document."""
    conds = [Document.workspace_id == af.workspace_id]
    levels = allowed_sensitivities(af)
    if not levels:
        conds.append(Document.id == uuid.UUID(int=0))  # impossible → deny all
        return conds
    conds.append(Document.sensitivity.in_(levels))
    if not af.wildcard:
        if af.collections:
            conds.append(Document.collection.in_(list(af.collections)))
        else:
            conds.append(Document.id == uuid.UUID(int=0))  # no collections → deny
    return conds


def count_documents(
    db: Session,
    af: AccessFilter,
    *,
    collection: str | None = None,
    since_days: int | None = None,
    title_contains: str | None = None,
) -> dict[str, Any]:
    conds = _doc_conditions(af)
    if collection:
        conds.append(Document.collection == collection)
    if since_days and since_days > 0:
        cutoff = datetime.now(UTC) - timedelta(days=since_days)
        conds.append(Document.updated_at >= cutoff)
    if title_contains:
        conds.append(Document.title.ilike(f"%{title_contains}%"))
    n = db.scalar(select(func.count()).select_from(Document).where(*conds)) or 0
    return {
        "count": int(n),
        "collection": collection or "all",
        "since_days": since_days,
        "title_contains": title_contains,
    }


def list_recent_documents(
    db: Session,
    af: AccessFilter,
    *,
    collection: str | None = None,
    limit: int = 10,
    title_contains: str | None = None,
) -> dict[str, Any]:
    limit = max(1, min(limit or 10, 25))
    conds = _doc_conditions(af)
    if collection:
        conds.append(Document.collection == collection)
    if title_contains:
        conds.append(Document.title.ilike(f"%{title_contains}%"))
    rows = list(
        db.scalars(
            select(Document)
            .where(*conds)
            .order_by(Document.updated_at.desc().nullslast(), Document.ingested_at.desc())
            .limit(limit)
        )
    )
    return {
        "items": [
            {
                "title": d.title,
                "collection": d.collection,
                "url": d.url,
                "date": d.updated_at.isoformat() if d.updated_at else None,
                "document_id": str(d.id),
            }
            for d in rows
        ],
        "returned": len(rows),
    }


def _as_int(v: Any) -> int | None:
    """Models sometimes send numbers as strings ('1'). Coerce safely."""
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def execute_tool(
    db: Session, af: AccessFilter, name: str, args: dict[str, Any]
) -> dict[str, Any]:
    """Dispatch a tool call by name. Unknown tool → error payload (the LLM
    sees it and recovers)."""
    try:
        if name == "count_documents":
            return count_documents(
                db,
                af,
                collection=args.get("collection"),
                since_days=_as_int(args.get("since_days")),
                title_contains=args.get("title_contains"),
            )
        if name == "list_recent_documents":
            return list_recent_documents(
                db,
                af,
                collection=args.get("collection"),
                limit=_as_int(args.get("limit")) or 10,
                title_contains=args.get("title_contains"),
            )
        return {"error": f"unknown tool {name!r}"}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:240]}
