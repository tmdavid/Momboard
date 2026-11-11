"""v0.5 tagging quality: app settings, per-tag floors/hints, taxonomy versioning.

Revision ID: 011_v05_tagging
Revises: 010_hypothesis_history_questions
Create Date: 2026-11-11

Adds (all additive, nothing is modified or dropped):
- app_settings: key/value store for UI-edited settings (the seller's company profile and the
  taxonomy version counter).
- tags.min_confidence (default 0.5), tags.negative_hint, tags.example, tags.added_in_version.
- conversations.taxonomy_version / tagged_at: which taxonomy tagged a call, and when. Existing
  calls get NULL ("tagged before versioning") so the UI can say they predate it.

Existing tags get added_in_version = 0 and existing calls NULL, so nothing is reported as
"added after tagging" until a tag is actually added after this migration.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011_v05_tagging"
down_revision: str = "010_hypothesis_history_questions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("key", sa.String(length=100), nullable=False, unique=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    with op.batch_alter_table("tags") as batch_op:
        batch_op.add_column(
            sa.Column("min_confidence", sa.Float(), nullable=False, server_default="0.5")
        )
        batch_op.add_column(sa.Column("negative_hint", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("example", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("added_in_version", sa.Integer(), nullable=False, server_default="0")
        )

    with op.batch_alter_table("conversations") as batch_op:
        batch_op.add_column(sa.Column("taxonomy_version", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("tagged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("conversations") as batch_op:
        batch_op.drop_column("tagged_at")
        batch_op.drop_column("taxonomy_version")
    with op.batch_alter_table("tags") as batch_op:
        batch_op.drop_column("added_in_version")
        batch_op.drop_column("example")
        batch_op.drop_column("negative_hint")
        batch_op.drop_column("min_confidence")
    op.drop_table("app_settings")
