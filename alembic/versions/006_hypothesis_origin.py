"""Add origin to hypotheses for evidence-gated intake (T48).

Revision ID: 006_hypothesis_origin
Revises: 005_synthesis_saved
Create Date: 2026-11-10

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "006_hypothesis_origin"
down_revision: str = "005_synthesis_saved"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # T48: how a hypothesis entered the board — ai (linker), human (manual intake),
    # or import. Existing rows default to 'ai' (the only pre-T48 producer).
    with op.batch_alter_table("hypotheses") as batch_op:
        batch_op.add_column(
            sa.Column(
                "origin",
                sa.String(length=20),
                nullable=False,
                server_default="ai",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("hypotheses") as batch_op:
        batch_op.drop_column("origin")
