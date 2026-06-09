"""run_automations(workspace_id) — the worker job.

For each enabled automation in the workspace:
  - pull inbound messages from the configured provider
  - dedupe against existing pending drafts for the same thread_ref
  - draft a reply via app.automations.draft.draft_reply
  - persist a Draft row (status='pending')
  - bump usage_counters + audit_log
  - record AutomationRun status + counts

ABSOLUTELY NO SEND. The runner only produces review queue items.

SCALE: today this is a single linear pass. At fan-out scale, enqueue
one sub-job per (automation, incoming) so they run in parallel; gate
provider fetch on a per-tenant token bucket; cache the voice profile.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.access import audit_chain
from app.access.grants import load_grant
from app.automations.draft import draft_reply
from app.automations.inbound import get_inbound_provider
from app.config import get_settings
from app.db import SessionLocal
from app.models import Automation, AutomationRun, Draft, Membership
from app.services.usage import record_usage

log = logging.getLogger("pioneer.automations")


def _now() -> datetime:
    return datetime.now(UTC)


async def run_automations(workspace_id_str: str) -> dict:
    workspace_id = uuid.UUID(workspace_id_str)
    settings = get_settings()
    provider = get_inbound_provider(settings.automations_inbound_provider)

    db: Session = SessionLocal()
    try:
        # Pick the workspace owner as the principal for retrieval —
        # automations run on behalf of the user.
        member = db.scalar(
            select(Membership).where(Membership.workspace_id == workspace_id).limit(1)
        )
        if member is None:
            return {"ok": False, "reason": "no_member"}
        user_id = member.user_id
        grants = load_grant(
            db, workspace_id=workspace_id, principal_type="user", principal_id=user_id
        )

        enabled = list(
            db.scalars(
                select(Automation).where(
                    Automation.workspace_id == workspace_id,
                    Automation.enabled.is_(True),
                )
            )
        )
        if not enabled:
            return {"ok": True, "skipped": True, "reason": "no_enabled_automations"}

        total_runs: list[uuid.UUID] = []
        total_drafts = 0
        total_tokens_in = 0
        total_tokens_out = 0

        for automation in enabled:
            run = AutomationRun(
                workspace_id=workspace_id,
                automation_id=automation.id,
                status="running",
                started_at=_now(),
            )
            db.add(run)
            db.commit()
            db.refresh(run)
            run_drafts = 0
            run_tokens_in = 0
            run_tokens_out = 0
            try:
                inbound = list(
                    provider.fetch(
                        automation_type=automation.type,
                        limit=settings.drafts_per_run_max,
                    )
                )
                run.inbound_seen = len(inbound)
                for incoming in inbound:
                    # Dedupe: if a pending draft already exists for this thread,
                    # skip — the user hasn't acted on the previous one.
                    existing = db.scalar(
                        select(Draft).where(
                            Draft.workspace_id == workspace_id,
                            Draft.automation_id == automation.id,
                            Draft.thread_ref == incoming.thread_ref,
                            Draft.status == "pending",
                        )
                    )
                    if existing is not None:
                        continue

                    result = await draft_reply(
                        db,
                        workspace_id=workspace_id,
                        grants=grants,
                        user_id=user_id,
                        incoming=incoming,
                    )

                    draft = Draft(
                        workspace_id=workspace_id,
                        automation_id=automation.id,
                        channel=incoming.channel,
                        thread_ref=incoming.thread_ref,
                        recipient=incoming.sender,
                        incoming_excerpt=incoming.incoming_text[:1000],
                        draft_body=result.body,
                        status="pending",
                    )
                    db.add(draft)
                    db.flush()

                    run_drafts += 1
                    run_tokens_in += result.usage.input_tokens
                    run_tokens_out += result.usage.output_tokens

                    record_usage(db, workspace_id=workspace_id, usage=result.usage)
                    audit_chain.append(
                        db,
                        workspace_id=workspace_id,
                        principal_type="system",
                        principal_id=None,
                        action="automation.draft",
                        resource_type="draft",
                        resource_id=draft.id,
                        decision="allow",
                        scope={
                            "automation_id": str(automation.id),
                            "channel": incoming.channel,
                            "thread_ref": incoming.thread_ref,
                            "tokens_in": result.usage.input_tokens,
                            "tokens_out": result.usage.output_tokens,
                            "provider": result.provider,
                            "model": result.model,
                            "sources_offered": result.sources_offered,
                        },
                    )
                    db.commit()

                run.drafts_created = run_drafts
                run.tokens_in = run_tokens_in
                run.tokens_out = run_tokens_out
                run.status = "success"
                run.finished_at = _now()
                db.commit()

                total_runs.append(run.id)
                total_drafts += run_drafts
                total_tokens_in += run_tokens_in
                total_tokens_out += run_tokens_out

            except Exception as e:  # noqa: BLE001
                log.exception("run_automations failed for automation %s", automation.id)
                run.status = "error"
                run.error = str(e)[:512]
                run.finished_at = _now()
                run.drafts_created = run_drafts
                run.tokens_in = run_tokens_in
                run.tokens_out = run_tokens_out
                db.commit()

        return {
            "ok": True,
            "automation_runs": [str(r) for r in total_runs],
            "drafts_created": total_drafts,
            "tokens_in": total_tokens_in,
            "tokens_out": total_tokens_out,
        }
    finally:
        db.close()
