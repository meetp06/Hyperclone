"""phase3 access control + audit chain

Revision ID: 3573899b3f4f
Revises: d5a8a1f072a2
Create Date: 2026-06-08 23:47:58.187130
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid as _uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3573899b3f4f"
down_revision: Union[str, None] = "d5a8a1f072a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# --- helpers ---------------------------------------------------------------


def _hmac_secret() -> bytes:
    """Read AUDIT_HMAC_KEY via the same Settings the runtime uses so the
    backfill chain matches what the API will compute later.
    """
    key = os.environ.get("AUDIT_HMAC_KEY", "")
    if not key:
        # Fall back to pydantic-settings (loads .env).
        from app.config import get_settings

        key = get_settings().audit_hmac_key
    if not key or key.startswith("REPLACE_ME"):
        raise RuntimeError(
            "AUDIT_HMAC_KEY must be set for the Phase-3 migration "
            "(generate with: python -c \"import secrets; print(secrets.token_urlsafe(64))\")"
        )
    return key.encode("utf-8")


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _chain(prev: bytes, payload: dict, *, secret: bytes) -> bytes:
    return hmac.new(secret, prev + _canonical(payload), hashlib.sha256).digest()


# --- upgrade ---------------------------------------------------------------


def upgrade() -> None:
    bind = op.get_bind()

    # --- new tables -------------------------------------------------------
    op.create_table(
        "access_grants",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("principal_type", sa.String(length=16), nullable=False),
        sa.Column("principal_id", sa.UUID(), nullable=False),
        sa.Column("sensitivity_max", sa.Integer(), nullable=False, server_default="-1"),
        sa.Column(
            "collections",
            postgresql.ARRAY(sa.String(length=64)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "actions",
            postgresql.ARRAY(sa.String(length=16)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "principal_type",
            "principal_id",
            name="uq_grant_workspace_principal",
        ),
    )
    op.create_index("ix_access_grants_principal_id", "access_grants", ["principal_id"])
    op.create_index("ix_access_grants_workspace_id", "access_grants", ["workspace_id"])

    op.create_table(
        "agent_keys",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("workspace_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_id"], ["workspaces.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_agent_keys_agent_id", "agent_keys", ["agent_id"])
    op.create_index("ix_agent_keys_key_hash", "agent_keys", ["key_hash"], unique=True)
    op.create_index("ix_agent_keys_workspace_id", "agent_keys", ["workspace_id"])

    # --- access-control columns (nullable first, backfill, then NOT NULL) -

    op.add_column(
        "memories",
        sa.Column("sensitivity", sa.String(length=16), nullable=True, server_default="internal"),
    )
    op.add_column(
        "memories",
        sa.Column("collection", sa.String(length=64), nullable=True, server_default="manual"),
    )
    bind.execute(
        sa.text(
            "UPDATE memories SET sensitivity = 'internal' WHERE sensitivity IS NULL"
        )
    )
    bind.execute(
        sa.text("UPDATE memories SET collection = 'manual' WHERE collection IS NULL")
    )
    op.alter_column("memories", "sensitivity", nullable=False)
    op.alter_column("memories", "collection", nullable=False)

    op.add_column(
        "documents",
        sa.Column("sensitivity", sa.String(length=16), nullable=True, server_default="internal"),
    )
    op.add_column(
        "documents",
        sa.Column("collection", sa.String(length=64), nullable=True),
    )
    bind.execute(
        sa.text("UPDATE documents SET sensitivity = 'internal' WHERE sensitivity IS NULL")
    )
    # Collection default = the provider name (notion, gmail, slack-dm, …).
    bind.execute(sa.text("UPDATE documents SET collection = provider WHERE collection IS NULL"))
    op.alter_column("documents", "sensitivity", nullable=False)
    op.alter_column("documents", "collection", nullable=False)

    # --- audit_log chain columns ----------------------------------------

    op.add_column("audit_log", sa.Column("seq", sa.BigInteger(), nullable=True))
    op.add_column(
        "audit_log",
        sa.Column("principal_type", sa.String(length=16), nullable=True, server_default="user"),
    )
    op.add_column("audit_log", sa.Column("principal_id", sa.UUID(), nullable=True))
    op.add_column(
        "audit_log",
        sa.Column("decision", sa.String(length=16), nullable=True, server_default="allow"),
    )
    op.add_column(
        "audit_log",
        sa.Column(
            "scope",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("audit_log", sa.Column("prev_hash", sa.LargeBinary(), nullable=True))
    op.add_column("audit_log", sa.Column("entry_hash", sa.LargeBinary(), nullable=True))

    # Fill principal_id + decision + scope for legacy rows.
    bind.execute(
        sa.text(
            "UPDATE audit_log SET principal_type = COALESCE(principal_type, 'user'), "
            "principal_id = COALESCE(principal_id, actor_user_id), "
            "decision = COALESCE(decision, 'allow'), "
            "scope = COALESCE(scope, '{}'::jsonb) "
            "WHERE seq IS NULL"
        )
    )

    # Compute per-workspace seq and chain for existing rows.
    secret = _hmac_secret()
    rows = bind.execute(
        sa.text(
            "SELECT id, workspace_id, principal_type, principal_id, actor_user_id, "
            "action, resource_type, resource_id, decision, scope, created_at "
            "FROM audit_log ORDER BY workspace_id, created_at, id"
        )
    ).mappings().all()

    prev_by_ws: dict[_uuid.UUID, tuple[int, bytes]] = {}  # ws -> (seq, hash)
    for r in rows:
        ws = r["workspace_id"]
        prev_seq, prev_hash = prev_by_ws.get(ws, (0, b"\x00" * 32))
        seq = prev_seq + 1
        payload = {
            "seq": seq,
            "workspace_id": str(ws),
            "principal_type": r["principal_type"] or "user",
            "principal_id": str(r["principal_id"]) if r["principal_id"] else None,
            "action": r["action"],
            "resource_type": r["resource_type"],
            "resource_id": str(r["resource_id"]) if r["resource_id"] else None,
            "decision": r["decision"] or "allow",
            "scope": r["scope"] or {},
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        entry_hash = _chain(prev_hash, payload, secret=secret)
        bind.execute(
            sa.text(
                "UPDATE audit_log SET seq = :seq, prev_hash = :prev, entry_hash = :eh "
                "WHERE id = :id"
            ),
            {"seq": seq, "prev": prev_hash, "eh": entry_hash, "id": r["id"]},
        )
        prev_by_ws[ws] = (seq, entry_hash)

    # Now flip to NOT NULL.
    op.alter_column("audit_log", "seq", nullable=False)
    op.alter_column("audit_log", "principal_type", nullable=False)
    op.alter_column("audit_log", "decision", nullable=False)
    op.alter_column("audit_log", "scope", nullable=False)
    op.alter_column("audit_log", "prev_hash", nullable=False)
    op.alter_column("audit_log", "entry_hash", nullable=False)
    op.create_index("ix_audit_log_principal_id", "audit_log", ["principal_id"])
    op.create_index("ix_audit_log_seq", "audit_log", ["seq"])
    op.create_unique_constraint(
        "uq_audit_log_workspace_seq", "audit_log", ["workspace_id", "seq"]
    )

    # --- seed default access grants ------------------------------------
    # One grant per existing membership so users keep their workspace-wide
    # read+write access (sensitivity_max=2 + collections=['*']).
    op.execute(
        """
        INSERT INTO access_grants
            (id, workspace_id, principal_type, principal_id,
             sensitivity_max, collections, actions, created_at)
        SELECT gen_random_uuid(), m.workspace_id, 'user', m.user_id,
               2, ARRAY['*'], ARRAY['read','write'], now()
        FROM memberships m
        ON CONFLICT (workspace_id, principal_type, principal_id) DO NOTHING
        """
    )

    # --- DB-level immutability trigger ----------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER audit_log_no_modify
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
        """
    )


# --- downgrade -------------------------------------------------------------


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_modify ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")

    op.drop_constraint("uq_audit_log_workspace_seq", "audit_log", type_="unique")
    op.drop_index("ix_audit_log_seq", table_name="audit_log")
    op.drop_index("ix_audit_log_principal_id", table_name="audit_log")
    op.drop_column("audit_log", "entry_hash")
    op.drop_column("audit_log", "prev_hash")
    op.drop_column("audit_log", "scope")
    op.drop_column("audit_log", "decision")
    op.drop_column("audit_log", "principal_id")
    op.drop_column("audit_log", "principal_type")
    op.drop_column("audit_log", "seq")

    op.drop_column("documents", "collection")
    op.drop_column("documents", "sensitivity")
    op.drop_column("memories", "collection")
    op.drop_column("memories", "sensitivity")

    op.drop_index("ix_agent_keys_workspace_id", table_name="agent_keys")
    op.drop_index("ix_agent_keys_key_hash", table_name="agent_keys")
    op.drop_index("ix_agent_keys_agent_id", table_name="agent_keys")
    op.drop_table("agent_keys")

    op.drop_index("ix_access_grants_workspace_id", table_name="access_grants")
    op.drop_index("ix_access_grants_principal_id", table_name="access_grants")
    op.drop_table("access_grants")
