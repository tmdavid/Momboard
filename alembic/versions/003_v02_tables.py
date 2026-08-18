"""Add v0.2 tables: staging_inbox, drifts, chats, digests, briefs cache.

Revision ID: 003_v02_tables
Revises: 002_hypotheses
Create Date: 2026-08-17

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003_v02_tables"
down_revision: str = "002_hypotheses"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # T34: Staging inbox — every automated source lands here first
    op.create_table(
        "staging_inbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(50), nullable=False),  # gmeet|drive|mcp|whisper
        sa.Column("source_ref", sa.String(500), nullable=False),  # dedupe key (e.g. Drive doc ID)
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("content_format", sa.String(50), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending_import",
        ),  # pending_import|imported|ignored|parse_error
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("conversation_id", sa.Integer(), nullable=True),  # set on import
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
        ),
    )
    op.create_index("ix_staging_inbox_source_ref", "staging_inbox", ["source_ref"], unique=True)
    op.create_index("ix_staging_inbox_status", "staging_inbox", ["status"])

    # T29: Drifts — detected contradictions between earlier and later statements
    op.create_table(
        "drifts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("contact_id", sa.Integer(), nullable=False),
        sa.Column("earlier_highlight_id", sa.Integer(), nullable=False),
        sa.Column("later_highlight_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False, server_default="change"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["earlier_highlight_id"], ["highlights.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["later_highlight_id"], ["highlights.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "kind IN ('contradiction', 'change')",
            name="ck_drifts_kind",
        ),
        sa.CheckConstraint(
            "status IN ('open', 'dismissed', 'confirmed')",
            name="ck_drifts_status",
        ),
    )
    op.create_index("ix_drifts_contact_id", "drifts", ["contact_id"])

    # T42: Chat conversations — per-user corpus chat storage
    op.create_table(
        "chats",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("turns", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_chats_user_id", "chats", ["user_id"])

    # T31: Digest tracking — idempotency key prevents duplicates
    op.create_table(
        "digest_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("iso_week", sa.String(10), nullable=False),  # e.g. "2026-W33"
        sa.Column("markdown", sa.Text(), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("iso_week"),
    )


def downgrade() -> None:
    op.drop_table("digest_log")
    op.drop_table("chats")
    op.drop_table("drifts")
    op.drop_index("ix_staging_inbox_status", table_name="staging_inbox")
    op.drop_index("ix_staging_inbox_source_ref", table_name="staging_inbox")
    op.drop_table("staging_inbox")
