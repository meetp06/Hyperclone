"""Inbound-message providers for the automations runner.

A provider yields `IncomingMessage`s that the runner turns into drafts.
The stub returns a few realistic samples so the whole flow demos without
LinkedIn/Gmail keys. Real providers swap in later behind the same
interface — no changes to the worker job.

SCALE: real providers stream from webhooks instead of polling, dedupe by
external message id, and track per-thread state so we never draft on
the same incoming twice.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class IncomingMessage:
    channel: str            # 'linkedin' | 'gmail' | …
    thread_ref: str         # opaque pointer back to the source thread
    sender: str             # display name or email
    subject: str | None
    incoming_text: str
    automation_type: str    # which automation should pick it up


class InboundMessageProvider(ABC):
    @abstractmethod
    def fetch(self, *, automation_type: str, limit: int) -> Iterable[IncomingMessage]: ...


class StubInboundProvider(InboundMessageProvider):
    """Realistic LinkedIn-DM + email samples. Same set every call so
    re-runs are deterministic and the worker can prove idempotency.
    """

    _LINKEDIN = [
        IncomingMessage(
            channel="linkedin",
            thread_ref="li:thread:demo-1",
            sender="Priya Shah",
            subject=None,
            incoming_text=(
                "Hey! Saw the Pioneer launch post — congrats. We're a 12-person ops team "
                "drowning in Slack→Notion handoff. Would love a 20-min walkthrough next week?"
            ),
            automation_type="auto_summarize_threads",
        ),
        IncomingMessage(
            channel="linkedin",
            thread_ref="li:thread:demo-2",
            sender="Marcus Lee",
            subject=None,
            incoming_text=(
                "Quick Q on pricing — does the Team tier limit MCP calls per agent? "
                "We'd want Claude Code + Cursor both reading from the same workspace."
            ),
            automation_type="auto_summarize_threads",
        ),
        IncomingMessage(
            channel="linkedin",
            thread_ref="li:thread:demo-3",
            sender="Sofia Martín",
            subject=None,
            incoming_text=(
                "Are you hiring? Founding-design profile, ex-Linear. Loved the orange-red "
                "accent in the screenshots — would happily chat."
            ),
            automation_type="auto_summarize_threads",
        ),
    ]

    _EMAIL = [
        IncomingMessage(
            channel="gmail",
            thread_ref="msg:demo-email-1",
            sender="evan@acme.com",
            subject="Re: Pioneer pilot — next steps",
            incoming_text=(
                "Thanks for the call. Three questions before legal can sign: "
                "1) where do you store our memory (on-prem option?), "
                "2) audit retention default, and "
                "3) which agents can read which collections out of the box."
            ),
            automation_type="daily_digest",
        ),
        IncomingMessage(
            channel="gmail",
            thread_ref="msg:demo-email-2",
            sender="ben@growthlab.co",
            subject="Pioneer + Notion integration",
            incoming_text=(
                "Hey — we're rolling out Notion across the company next month. "
                "Want to make sure Pioneer's connector handles databases too, not just pages. "
                "Any docs you can share?"
            ),
            automation_type="daily_digest",
        ),
    ]

    def fetch(self, *, automation_type: str, limit: int):
        pool = list(self._LINKEDIN) + list(self._EMAIL)
        matching = [m for m in pool if m.automation_type == automation_type]
        return matching[:limit]


def get_inbound_provider(name: str | None = None) -> InboundMessageProvider:
    """Single factory; today only stub. Returns the same instance per process."""
    return _STUB


_STUB = StubInboundProvider()
