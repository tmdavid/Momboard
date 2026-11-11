"""Hypothesis band history, validation questions, link review audit (Hypotheses PRD P1).

Revision ID: 010_hypothesis_history_questions
Revises: 009_decision_owner_area_draft
Create Date: 2026-11-11

Adds:
- hypothesis_band_events: one row per grounding-band change, with the causing link.
- hypothesis_questions: validation questions saved at intake (asked_at null until asked).
- hypothesis_links.reviewed_by / reviewed_at: who confirmed/rejected a link, and when.

Additive only. No existing data is modified; history starts from this migration.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "010_hypothesis_history_questions"
down_revision: str = "009_decision_owner_area_draft"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hypothesis_band_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "hypothesis_id",
            sa.Integer(),
            sa.ForeignKey("hypotheses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_band", sa.String(length=20), nullable=True),
        sa.Column("to_band", sa.String(length=20), nullable=False),
        sa.Column(
            "cause_link_id",
            sa.Integer(),
            sa.ForeignKey("hypothesis_links.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_hypothesis_band_events_hypothesis_id",
        "hypothesis_band_events",
        ["hypothesis_id"],
    )

    op.create_table(
        "hypothesis_questions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "hypothesis_id",
            sa.Integer(),
            sa.ForeignKey("hypotheses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_hypothesis_questions_hypothesis_id",
        "hypothesis_questions",
        ["hypothesis_id"],
    )

    with op.batch_alter_table("hypothesis_links") as batch_op:
        batch_op.add_column(sa.Column("reviewed_by", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("hypothesis_links") as batch_op:
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by")
    op.drop_index("ix_hypothesis_questions_hypothesis_id", table_name="hypothesis_questions")
    op.drop_table("hypothesis_questions")
    op.drop_index(
        "ix_hypothesis_band_events_hypothesis_id", table_name="hypothesis_band_events"
    )
    op.drop_table("hypothesis_band_events")
