"""Build a 'voice' style profile from the user's own writing in memory.

Phase-4 implementation: pull the most recent N memories authored by the
seed/owner user (or, when not available, the most recent N memories at
all) and present a few short excerpts as exemplars in the draft prompt.

SCALE: recomputing the exemplars on every draft is fine for a single
user demo. At scale, cache a precomputed `voice_profile` (length, tone
adjectives, signature opener/closer phrases) per user and refresh
nightly.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Membership, Memory


@dataclass(frozen=True)
class VoiceExample:
    title: str
    snippet: str


def build_voice_examples(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID | None = None,
    limit: int = 5,
    snippet_chars: int = 300,
) -> list[VoiceExample]:
    """Return up to `limit` writing examples in the user's voice."""

    if user_id is None:
        m = db.scalar(
            select(Membership)
            .where(Membership.workspace_id == workspace_id)
            .order_by(Membership.id)
            .limit(1)
        )
        user_id = m.user_id if m else None

    base = select(Memory).where(Memory.workspace_id == workspace_id)
    if user_id is not None:
        owned = base.where(Memory.author_user_id == user_id).order_by(
            Memory.created_at.desc()
        )
        rows = list(db.scalars(owned.limit(limit)))
    else:
        rows = []

    # Fall back to any recent memories so brand-new workspaces still show
    # *some* style — empty profile would produce sterile drafts.
    if len(rows) < limit:
        rest = list(
            db.scalars(
                base.where(Memory.id.notin_([r.id for r in rows] or [uuid.uuid4()]))
                .order_by(Memory.created_at.desc())
                .limit(limit - len(rows))
            )
        )
        rows.extend(rest)

    out: list[VoiceExample] = []
    for r in rows:
        text = (r.body or "").strip().replace("\n", " ")
        if not text:
            continue
        out.append(VoiceExample(title=r.title, snippet=text[:snippet_chars]))
    return out
