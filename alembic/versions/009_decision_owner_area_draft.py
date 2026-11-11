"""Decision owner_id + area + draft status (Decisions PRD P1).

Revision ID: 009_decision_owner_area_draft
Revises: 008_decision_snapshots
Create Date: 2026-11-11
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "009_decision_owner_area_draft"
down_revision: str = "008_decision_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # owner_id + area, and extend the status CHECK to allow 'draft'. recreate the
    # CHECK constraint by name inside a batch so SQLite accepts the change.
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.add_column(sa.Column("owner_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("area", sa.String(length=100), nullable=True))
        batch_op.drop_constraint("ck_decisions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_decisions_status",
            "status IN ('draft', 'proposed', 'decided', 'superseded')",
        )


def downgrade() -> None:
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.drop_constraint("ck_decisions_status", type_="check")
        batch_op.create_check_constraint(
            "ck_decisions_status",
            "status IN ('proposed', 'decided', 'superseded')",
        )
        batch_op.drop_column("area")
        batch_op.drop_column("owner_id")
