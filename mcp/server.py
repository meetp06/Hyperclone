"""Pioneer MCP server (Phase 3).

External agents (Claude Code, Cursor, etc.) reach Pioneer's memory only
through this server. Auth is a per-agent bearer key minted via
`POST /agents/{id}/keys`. The key resolves to a Principal whose grants
gate the read at filter-construction time — disallowed chunks never leave
Qdrant.

Pass the key from the MCP client config, e.g. via an env var the launcher
substitutes into the server command, or via the MCP transport's headers
where supported. We accept the key from either:
  - `PIONEER_AGENT_KEY` env var (works with stdio launchers everywhere)
  - `PIONEER_MCP_API_KEY` (Phase-2 fallback; only honored when APP_ENV=dev)

SCALE: the env-var fallback is dev-only. In production, agent keys flow
through proper MCP transport auth (SSE bearer header or per-session
handshake) and rotate via short-TTL JWTs.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from sqlalchemy import select  # noqa: E402

from app.access import audit_chain  # noqa: E402
from app.access.policy import allowed_filter  # noqa: E402
from app.access.principal import Principal, _resolve_agent  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import User, Workspace  # noqa: E402
from app.services.memory import search_documents, search_memory  # noqa: E402

settings = get_settings()
mcp = FastMCP("pioneer")


def _principal_from_env() -> Principal:
    """Resolve the calling principal from env-supplied agent key.

    Three paths:
    1. `PIONEER_AGENT_KEY` (Phase 3 normal path) — resolves through the
       same agent-key lookup the API uses; full deny-by-default applies.
    2. `PIONEER_MCP_API_KEY` matches the dev fallback (only when
       APP_ENV=dev) — resolves to the seeded workspace + first user
       (legacy Phase 2 behavior, kept so the local smoke test keeps
       working without minting a key first).
    3. Otherwise PermissionError.
    """
    agent_key = os.environ.get("PIONEER_AGENT_KEY")
    if agent_key:
        db = SessionLocal()
        try:
            p = _resolve_agent(agent_key, db)
            if p is None:
                raise PermissionError("invalid or revoked PIONEER_AGENT_KEY")
            db.commit()  # commit last_used_at update
            return p
        finally:
            db.close()

    if settings.app_env != "dev":
        raise PermissionError("PIONEER_AGENT_KEY required outside dev")

    legacy = os.environ.get("PIONEER_MCP_API_KEY", "")
    if not legacy or legacy != settings.mcp_api_key:
        raise PermissionError("missing PIONEER_AGENT_KEY (or dev PIONEER_MCP_API_KEY)")

    # Legacy dev path — synthesize a Principal with the seed user's grant.
    db = SessionLocal()
    try:
        ws = db.scalar(select(Workspace).order_by(Workspace.created_at).limit(1))
        if ws is None:
            raise RuntimeError("no workspace — run seed.py")
        user = db.scalar(select(User).order_by(User.created_at).limit(1))
        if user is None:
            raise RuntimeError("no user — run seed.py")
        from app.access.grants import load_grant

        grants = load_grant(
            db, workspace_id=ws.id, principal_type="user", principal_id=user.id
        )
        return Principal(type="user", id=user.id, workspace_id=ws.id, grants=grants)
    finally:
        db.close()


@mcp.tool(name="search_memory")
def search_memory_tool(query: str, top_k: int = 5) -> dict:
    """Semantic search over Pioneer workspace memory.

    Args:
        query: natural-language search string
        top_k: max number of items to return (1-25)
    """
    if top_k < 1 or top_k > 25:
        raise ValueError("top_k must be between 1 and 25")

    principal = _principal_from_env()
    af = allowed_filter(principal.workspace_id, principal.grants)

    db = SessionLocal()
    try:
        mem = search_memory(
            db=db,
            workspace_id=principal.workspace_id,
            principal_type=principal.type,
            principal_id=principal.id,
            access_filter=af,
            query=query,
            top_k=top_k,
        )
        docs = search_documents(
            db=db,
            workspace_id=principal.workspace_id,
            principal_type=principal.type,
            principal_id=principal.id,
            access_filter=af,
            query=query,
            top_k=top_k,
        )

        # Surface an explicit denial hint when nothing came back due to grants.
        return {
            "workspace_id": str(principal.workspace_id),
            "principal": {"type": principal.type, "id": str(principal.id)},
            "query": query,
            "denied_no_grant": not af.allows_any_read,
            "memory_hits": [
                {
                    "kind": "memory",
                    "id": str(r.memory.id),
                    "title": r.memory.title,
                    "body": r.memory.body,
                    "sensitivity": r.memory.sensitivity,
                    "collection": r.memory.collection,
                    "score": r.score,
                    "created_at": r.memory.created_at.isoformat(),
                }
                for r in mem
            ],
            "document_hits": [
                {
                    "kind": "document",
                    "id": str(r.document.id),
                    "title": r.document.title,
                    "url": r.document.url,
                    "provider": r.document.provider,
                    "sensitivity": r.document.sensitivity,
                    "collection": r.document.collection,
                    "chunk_index": r.chunk_index,
                    "score": r.score,
                }
                for r in docs
            ],
        }
    finally:
        db.close()


@mcp.tool(name="verify_audit_integrity")
def verify_audit_tool() -> dict:
    """Recompute the workspace audit chain. Returns ok, total entries,
    and the seq of the first tamper if any.
    """
    principal = _principal_from_env()
    db = SessionLocal()
    try:
        r = audit_chain.verify(db, principal.workspace_id)
        return {
            "ok": r.ok,
            "total": r.total,
            "broken_at_seq": r.broken_at_seq,
            "head_hash": r.head_hash_hex,
        }
    finally:
        db.close()


if __name__ == "__main__":
    mcp.run()
