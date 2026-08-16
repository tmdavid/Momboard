"""Add hypotheses and hypothesis_links tables.

Revision ID: 002_hypotheses
Revises: 001_initial
Create Date: 2026-08-16

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "002_hypotheses"
down_revision: str = "001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Hypotheses
    op.create_table(
        "hypotheses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("segment", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_hypotheses_status", "hypotheses", ["status"])

    # Hypothesis links
    op.create_table(
        "hypothesis_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("hypothesis_id", sa.Integer(), nullable=False),
        sa.Column("highlight_id", sa.Integer(), nullable=False),
        sa.Column("stance", sa.String(20), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("origin", sa.String(20), nullable=False, server_default="ai"),
        sa.Column("status", sa.String(20), nullable=False, server_default="suggested"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"], ["hypotheses.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["highlight_id"], ["highlights.id"], ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "stance IN ('supports', 'contradicts')",
            name="ck_hypothesis_links_stance",
        ),
    )
    op.create_index(
        "ix_hypothesis_links_hypothesis_id", "hypothesis_links", ["hypothesis_id"]
    )
    op.create_index(
        "ix_hypothesis_links_highlight_id", "hypothesis_links", ["highlight_id"]
    )


def downgrade() -> None:
    op.drop_table("hypothesis_links")
    op.drop_table("hypotheses")
