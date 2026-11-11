"""API tokens and the MCP audit log.

Revision ID: 012_api_tokens_mcp_audit
Revises: 011_v05_tagging
Create Date: 2026-11-11

Adds two new tables and changes nothing that exists:
- api_tokens: bearer tokens for scripts and MCP clients (only a SHA-256 hash is stored).
- mcp_calls: audit log of MCP tool calls (argument names and short values, never transcript text).
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012_api_tokens_mcp_audit"
down_revision: str = "011_v05_tagging"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("prefix", sa.String(length=8), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_token_hash"),
    )
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])

    op.create_table(
        "mcp_calls",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_id", sa.Integer(), sa.ForeignKey("api_tokens.id"), nullable=True),
        sa.Column("token_prefix", sa.String(length=8), nullable=True),
        sa.Column("tool", sa.String(length=100), nullable=False),
        sa.Column("args_summary", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mcp_calls_token_id", "mcp_calls", ["token_id"])
    op.create_index("ix_mcp_calls_created_at", "mcp_calls", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_mcp_calls_created_at", table_name="mcp_calls")
    op.drop_index("ix_mcp_calls_token_id", table_name="mcp_calls")
    op.drop_table("mcp_calls")
    op.drop_index("ix_api_tokens_user_id", table_name="api_tokens")
    op.drop_table("api_tokens")
