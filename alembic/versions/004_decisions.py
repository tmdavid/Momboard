"""Add decisions tables (T40).

Revision ID: 004_decisions
Revises: 003_v02_tables
Create Date: 2026-08-17

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "004_decisions"
down_revision: str = "003_v02_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # T40: Decisions — first-class evidence-backed decisions
    op.create_table(
        "decisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("rationale_md", sa.Text(), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="proposed",
        ),  # proposed|decided|superseded
        sa.Column(
            "integrity",
            sa.String(20),
            nullable=False,
            server_default="ok",
        ),  # ok|undermined
        sa.Column("integrity_reasons", sa.JSON(), nullable=True),
        sa.Column("hypothesis_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("superseded_by", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"], ["hypotheses.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["superseded_by"], ["decisions.id"], ondelete="SET NULL"
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'decided', 'superseded')",
            name="ck_decisions_status",
        ),
        sa.CheckConstraint(
            "integrity IN ('ok', 'undermined')",
            name="ck_decisions_integrity",
        ),
    )

    # T40: Decision evidence — links decisions to highlights (ON DELETE RESTRICT)
    op.create_table(
        "decision_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("decision_id", sa.Integer(), nullable=False),
        sa.Column("highlight_id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["decision_id"], ["decisions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["highlight_id"], ["highlights.id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_decision_evidence_decision_id", "decision_evidence", ["decision_id"]
    )
    op.create_index(
        "ix_decision_evidence_highlight_id", "decision_evidence", ["highlight_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_decision_evidence_highlight_id", table_name="decision_evidence")
    op.drop_index("ix_decision_evidence_decision_id", table_name="decision_evidence")
    op.drop_table("decision_evidence")
    op.drop_table("decisions")
