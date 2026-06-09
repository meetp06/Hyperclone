"""Seed Pioneer with one workspace, one user, demo connectors/agents/automations,
and ~10 demo memories so the dashboard has real content on first run.

Usage:
    uv run python -m app.seed            # idempotent: skips if seeded
    uv run python -m app.seed --reset    # wipe domain data first
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models import (
    Agent,
    AuditLog,
    Automation,
    Connector,
    Membership,
    Memory,
    UsageCounter,
    User,
    Workspace,
)

SEED_EMAIL = "meetp0006@gmail.com"
SEED_NAME = "Meet"
SEED_WORKSPACE = "Pioneer HQ"

DEMO_MEMORIES: list[tuple[str, str, str]] = [
    (
        "Q3 launch goals",
        "Ship Pioneer Phase 1 by end of Q3: MCP server live, 3 connectors GA "
        "(Notion, Linear, GitHub), and a shared memory store every agent in the "
        "company can read from.",
        "manual",
    ),
    (
        "Customer call: Acme — workflow pain",
        "Acme's ops team rewrites the same Slack threads into Notion docs every "
        "week. They want a memory layer that captures the thread + decision + "
        "owner without copy-paste. Willing to pay $30/seat.",
        "notes",
    ),
    (
        "Architecture decision: vector store = Qdrant",
        "Chose Qdrant over pgvector for Phase 1: payload-filterable, sane HNSW, "
        "and on-prem story when enterprise asks. EmbeddingProvider interface "
        "keeps us free to swap models without touching service layer.",
        "decision",
    ),
    (
        "Hiring: founding designer",
        "Looking for a founding designer who's shipped dev-tool UIs. Strong "
        "opinions on density and keyboard-first interactions. Refs welcome.",
        "hiring",
    ),
    (
        "Onboarding script v1",
        "New workspace gets a 90-second tour: connect 1 source, file your first "
        "memory, run a chat query, see audit log. Drop-off measured at each step.",
        "playbook",
    ),
    (
        "Pricing draft",
        "Free tier: 1 workspace, 3 connectors, 10k memories. Team: $20/seat, "
        "unlimited connectors, audit export. Enterprise: SSO, on-prem vectors, "
        "custom retention.",
        "pricing",
    ),
    (
        "Incident: Qdrant collection drift",
        "On 2026-06-01 a hot reload created two collections with mismatched dims. "
        "Fix: VectorStore.ensure_collection now asserts dim against settings "
        "before insert. Backfill script written.",
        "incident",
    ),
    (
        "MCP integration plan",
        "Expose search_memory + write_memory as MCP tools. Auth via per-workspace "
        "API key. Claude Code, Cursor, and our own agents share the same surface — "
        "no special-casing.",
        "plan",
    ),
    (
        "Sales objection: 'why not just Notion?'",
        "Notion is a doc store, not a memory layer for agents. Pioneer indexes, "
        "audits, and exposes memory to LLMs over MCP. Use both: Notion for humans, "
        "Pioneer for agents.",
        "sales",
    ),
    (
        "Brand notes — orange-red accent",
        "Accent #FF4A1C. Used sparingly: primary CTAs, active states, and the "
        "Remember button. Everything else stays in the warm-neutral dark palette.",
        "brand",
    ),
]

DEMO_CONNECTORS = [
    ("notion", "disconnected", None),
    ("github", "disconnected", None),
    ("slack", "disconnected", None),
    ("linear", "disconnected", None),
    ("gmail", "disconnected", None),
]

DEMO_AGENTS = [
    ("claude_code", "disconnected"),
    ("cursor", "disconnected"),
    ("chatgpt", "disconnected"),
]

DEMO_AUTOMATIONS = [
    ("daily_digest", False),
    ("weekly_review", False),
    ("auto_summarize_threads", False),
]


def _wipe(db: Session) -> None:
    for model in (
        AuditLog,
        Memory,
        UsageCounter,
        Automation,
        Agent,
        Connector,
        Membership,
        Workspace,
        User,
    ):
        db.execute(delete(model))
    db.commit()


def seed(reset: bool = False, include_memories: bool = True) -> None:
    db = SessionLocal()
    try:
        if reset:
            print("[seed] wiping domain data...", file=sys.stderr)
            _wipe(db)

        user = db.scalar(select(User).where(User.email == SEED_EMAIL))
        if user is None:
            user = User(email=SEED_EMAIL, name=SEED_NAME)
            db.add(user)
            db.flush()
            print(f"[seed] user created: {user.email} ({user.id})", file=sys.stderr)
        else:
            print(f"[seed] user exists: {user.email} ({user.id})", file=sys.stderr)

        ws = db.scalar(select(Workspace).where(Workspace.name == SEED_WORKSPACE))
        if ws is None:
            ws = Workspace(name=SEED_WORKSPACE, plan="free")
            db.add(ws)
            db.flush()
            print(f"[seed] workspace created: {ws.name} ({ws.id})", file=sys.stderr)
        else:
            print(f"[seed] workspace exists: {ws.name} ({ws.id})", file=sys.stderr)

        m = db.scalar(
            select(Membership).where(
                Membership.user_id == user.id, Membership.workspace_id == ws.id
            )
        )
        if m is None:
            db.add(Membership(user_id=user.id, workspace_id=ws.id, role="owner"))
            print("[seed] membership created", file=sys.stderr)

        for provider, status_, label in DEMO_CONNECTORS:
            if not db.scalar(
                select(Connector).where(
                    Connector.workspace_id == ws.id, Connector.provider == provider
                )
            ):
                db.add(
                    Connector(
                        workspace_id=ws.id,
                        provider=provider,
                        status=status_,
                        account_label=label,
                    )
                )

        for provider, status_ in DEMO_AGENTS:
            if not db.scalar(
                select(Agent).where(Agent.workspace_id == ws.id, Agent.provider == provider)
            ):
                db.add(Agent(workspace_id=ws.id, provider=provider, status=status_))

        for type_, enabled in DEMO_AUTOMATIONS:
            if not db.scalar(
                select(Automation).where(
                    Automation.workspace_id == ws.id, Automation.type == type_
                )
            ):
                db.add(Automation(workspace_id=ws.id, type=type_, enabled=enabled))

        period = datetime.now(UTC).strftime("%Y-%m")
        uc = db.get(UsageCounter, {"workspace_id": ws.id, "period": period})
        if uc is None:
            db.add(UsageCounter(workspace_id=ws.id, period=period, tokens_used=0))

        db.commit()

        if include_memories:
            existing = db.scalar(
                select(Memory).where(Memory.workspace_id == ws.id).limit(1)
            )
            if existing is None:
                # Lazy import: pulls fastembed (slow first-call) only when we
                # actually need to write memories.
                from app.services.memory import write_memory

                for title, body, source in DEMO_MEMORIES:
                    write_memory(
                        db=db,
                        workspace_id=ws.id,
                        author_user_id=user.id,
                        title=title,
                        body=body,
                        source=source,
                    )
                print(f"[seed] inserted {len(DEMO_MEMORIES)} memories", file=sys.stderr)
            else:
                print("[seed] memories already present, skipping", file=sys.stderr)

        print(f"\n[seed] done.\n  user_id={user.id}\n  workspace_id={ws.id}\n  email={user.email}")
    finally:
        db.close()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true", help="wipe domain data first")
    p.add_argument(
        "--no-memories",
        action="store_true",
        help="skip memory writes (skips fastembed load)",
    )
    args = p.parse_args()
    seed(reset=args.reset, include_memories=not args.no_memories)


if __name__ == "__main__":
    main()
