"""Arq worker entrypoint.

Run in dev:
    cd backend && uv run arq app.worker.main.WorkerSettings

Run in docker-compose:
    Service `pioneer-worker` invokes the same command inside the image.

The API never ingests — it only enqueues. All real work lives in this process.

SCALE: split into per-tenant or per-provider queues by passing a queue_name
to functions and running multiple worker fleets; today everything shares
the arq default queue.
"""

from __future__ import annotations

from urllib.parse import urlparse

import os

from arq.connections import RedisSettings

from app.config import get_settings
from app.worker.jobs import ping, run_automations, sync_connector


async def _on_startup(ctx: dict) -> None:
    """Optional dev hook: replace the Notion connector with a fake in-memory
    impl. Active only when env `PIONEER_FAKE_NOTION=1`. Useful for demoing
    the full queue → worker → ingestion → status path before the user has
    real Notion OAuth credentials.
    """
    if os.environ.get("PIONEER_FAKE_NOTION") == "1":
        # Local import so production paths never load the fake.
        import sys
        from pathlib import Path
        repo_root = Path(__file__).resolve().parents[3]
        scripts_dir = str(repo_root / "backend")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from scripts._fake_notion_sync import FakeNotion  # noqa: E402
        from app.connectors import registry
        registry._REGISTRY["notion"] = FakeNotion()
        ctx["log"].info("[dev] PIONEER_FAKE_NOTION=1 — registered FakeNotion") if "log" in ctx else None


def _redis_settings_from_url(url: str) -> RedisSettings:
    p = urlparse(url)
    return RedisSettings(
        host=p.hostname or "localhost",
        port=p.port or 6379,
        database=int((p.path or "/0").lstrip("/") or 0),
        password=p.password,
    )


_settings = get_settings()


class WorkerSettings:
    functions = [ping, sync_connector, run_automations]
    redis_settings = _redis_settings_from_url(_settings.redis_url)
    max_jobs = _settings.arq_max_jobs
    keep_result = 3600  # seconds
    job_timeout = 60 * 30  # 30 min — large Notion workspaces can take a while
    on_startup = _on_startup
