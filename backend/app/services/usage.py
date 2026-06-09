"""Per-workspace LLM usage accounting.

Bumps `usage_counters(workspace_id, period='YYYY-MM').tokens_used` by
(in + out) tokens. Idempotent at the SQL level via upsert.

SCALE: today every chat / draft does its own UPDATE — fine to a few
hundred/sec/workspace. At scale, accumulate per-workspace in a Redis
counter and flush to PG every N seconds.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.llm import LLMUsage


def _period(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).strftime("%Y-%m")


def record_usage(
    db: Session,
    *,
    workspace_id: uuid.UUID,
    usage: LLMUsage,
) -> None:
    if usage.total <= 0:
        return
    db.execute(
        text(
            """
            INSERT INTO usage_counters (workspace_id, period, tokens_used)
            VALUES (:w, :p, :t)
            ON CONFLICT (workspace_id, period)
            DO UPDATE SET tokens_used = usage_counters.tokens_used + EXCLUDED.tokens_used
            """
        ),
        {"w": str(workspace_id), "p": _period(), "t": usage.total},
    )
