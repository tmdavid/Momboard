"""Add saved flag to analyses for kept syntheses (T45).

Revision ID: 005_synthesis_saved
Revises: 004_decisions
Create Date: 2026-09-04

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "005_synthesis_saved"
down_revision: str = "004_decisions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # T45: mark syntheses (analyses) the user explicitly keeps.
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "saved",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.drop_column("saved")
