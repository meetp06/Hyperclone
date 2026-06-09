"""Phase-3 policy engine — pure functions, deny-by-default.

Translates a principal's grants into an `AccessFilter`, then into a
Qdrant filter that the vector store applies inside the query. Disallowed
chunks are never retrieved.

SCALE: in-process policy compiled per-request. At enterprise scale,
externalize to Cedar/OPA with policy-as-code per workspace and cache the
compiled filter in Redis with grant-revision invalidation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

# Ordinal ladder: higher number = more sensitive.
SENSITIVITY_RANK: dict[str, int] = {"public": 0, "internal": 1, "restricted": 2}
SENSITIVITY_LEVELS: tuple[str, ...] = ("public", "internal", "restricted")

WILDCARD = "*"
NO_READ = -1


@dataclass(frozen=True)
class GrantSet:
    """A principal's compiled grants.

    `sensitivity_max == NO_READ` means no read access at all.
    `WILDCARD` in `collections` means any collection is allowed.
    """

    sensitivity_max: int = NO_READ
    collections: frozenset[str] = field(default_factory=frozenset)
    actions: frozenset[str] = field(default_factory=frozenset)

    @property
    def can_read(self) -> bool:
        return self.sensitivity_max >= 0 and "read" in self.actions

    @property
    def can_write_action(self) -> bool:
        return "write" in self.actions

    @property
    def is_wildcard_collection(self) -> bool:
        return WILDCARD in self.collections


@dataclass(frozen=True)
class AccessFilter:
    """Compiled Qdrant-friendly access filter for one principal."""

    workspace_id: uuid.UUID
    sensitivity_max: int = NO_READ
    collections: frozenset[str] = field(default_factory=frozenset)
    wildcard: bool = False

    @property
    def allows_any_read(self) -> bool:
        return self.sensitivity_max >= 0 and (self.wildcard or bool(self.collections))


def allowed_filter(workspace_id: uuid.UUID, grants: GrantSet) -> AccessFilter:
    """Compile a workspace-scoped filter for the principal."""
    if not grants.can_read:
        return AccessFilter(workspace_id=workspace_id, sensitivity_max=NO_READ)
    return AccessFilter(
        workspace_id=workspace_id,
        sensitivity_max=grants.sensitivity_max,
        collections=frozenset(c for c in grants.collections if c != WILDCARD),
        wildcard=grants.is_wildcard_collection,
    )


def can_read(grants: GrantSet, sensitivity: str, collection: str) -> bool:
    if not grants.can_read:
        return False
    rank = SENSITIVITY_RANK.get(sensitivity)
    if rank is None or rank > grants.sensitivity_max:
        return False
    if grants.is_wildcard_collection:
        return True
    return collection in grants.collections


def can_write(grants: GrantSet, sensitivity: str, collection: str) -> bool:
    if not grants.can_write_action:
        return False
    rank = SENSITIVITY_RANK.get(sensitivity)
    if rank is None or rank > grants.sensitivity_max:
        return False
    if grants.is_wildcard_collection:
        return True
    return collection in grants.collections


def allowed_sensitivities(af: AccessFilter) -> list[str]:
    """Levels (by name) the filter admits, in ascending order."""
    if af.sensitivity_max < 0:
        return []
    return [
        name for name, rank in SENSITIVITY_RANK.items() if rank <= af.sensitivity_max
    ]


def to_qdrant_filter(af: AccessFilter):
    """Translate the policy filter into a concrete Qdrant `Filter`.

    Imported lazily so unit tests can run without the qdrant client installed.
    The returned filter always pins `workspace_id` (tenant boundary), the set
    of allowed sensitivities, and the collection allow-list. When the
    principal has no read access we produce an unsatisfiable filter so
    the search returns zero hits without leaking counts.
    """
    from qdrant_client.http import models as qm

    must: list = [
        qm.FieldCondition(
            key="workspace_id",
            match=qm.MatchValue(value=str(af.workspace_id)),
        )
    ]

    if af.sensitivity_max < 0:
        # No read at all — match an impossible value.
        must.append(
            qm.FieldCondition(
                key="sensitivity",
                match=qm.MatchValue(value="__deny__"),
            )
        )
        return qm.Filter(must=must)

    # Restrict to allowed sensitivity levels.
    levels = allowed_sensitivities(af)
    must.append(
        qm.FieldCondition(key="sensitivity", match=qm.MatchAny(any=list(levels)))
    )

    # Collection allow-list. Wildcard skips this constraint.
    if not af.wildcard:
        if not af.collections:
            must.append(
                qm.FieldCondition(
                    key="collection",
                    match=qm.MatchValue(value="__deny__"),
                )
            )
        else:
            must.append(
                qm.FieldCondition(
                    key="collection",
                    match=qm.MatchAny(any=list(af.collections)),
                )
            )

    return qm.Filter(must=must)
