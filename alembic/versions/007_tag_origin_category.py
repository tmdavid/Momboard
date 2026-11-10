"""Add origin + category to tags for custom-taxonomy grouping (T47).

Revision ID: 007_tag_origin_category
Revises: 006_hypothesis_origin
Create Date: 2026-11-10

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "007_tag_origin_category"
down_revision: str = "006_hypothesis_origin"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # origin: "core" = shipped seed taxonomy, "custom" = user-created.
    # Existing rows default to "custom"; the idempotent seed re-stamps the 12
    # shipped tags back to "core" on the next `python -m app.seed` run, and the
    # one-time DB backfill fixes any already-present rows.
    # category: free-text grouping label for custom tags; nullable.
    with op.batch_alter_table("tags") as batch_op:
        batch_op.add_column(
            sa.Column(
                "origin",
                sa.String(length=20),
                nullable=False,
                server_default="custom",
            )
        )
        batch_op.add_column(
            sa.Column(
                "category",
                sa.String(length=100),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tags") as batch_op:
        batch_op.drop_column("category")
        batch_op.drop_column("origin")
