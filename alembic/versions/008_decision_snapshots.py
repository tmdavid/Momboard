"""Decision evidence snapshots + integrity_checked_at (Decisions PRD P0).

Revision ID: 008_decision_snapshots
Revises: 007_tag_origin_category
Create Date: 2026-11-11

Adds a per-receipt snapshot (quote/company/conversation/date) to decision_evidence
so a receipt survives a Retag that replaces the live highlight, makes highlight_id
nullable (SET NULL) + adds invalid_reason for the integrity hook, and adds
integrity_checked_at to decisions. Backfills snapshots for existing evidence rows
from the current highlights and their conversations.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "008_decision_snapshots"
down_revision: str = "007_tag_origin_category"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # decisions.integrity_checked_at
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.add_column(sa.Column("integrity_checked_at", sa.DateTime(timezone=True), nullable=True))

    # decision_evidence: snapshot columns + nullable highlight_id (SET NULL) + invalid_reason.
    # recreate='always' rebuilds the table so the highlight_id FK can switch from
    # ondelete=RESTRICT (not null) to ondelete=SET NULL (nullable) on SQLite.
    with op.batch_alter_table(
        "decision_evidence",
        recreate="always",
        table_args=(
            sa.ForeignKeyConstraint(["decision_id"], ["decisions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["highlight_id"], ["highlights.id"], ondelete="SET NULL"),
        ),
    ) as batch_op:
        batch_op.add_column(sa.Column("quote_snapshot", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("company_name", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("conversation_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("conversation_date", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("cited_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())
        )
        batch_op.add_column(sa.Column("invalid_reason", sa.String(length=50), nullable=True))
        batch_op.alter_column("highlight_id", existing_type=sa.Integer(), nullable=True)

    # Backfill snapshots for existing receipts from the live highlight + conversation.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            """
            SELECT de.id AS ev_id, h.quote AS quote, h.conversation_id AS conv_id,
                   co.name AS company_name, c.happened_at AS happened_at
            FROM decision_evidence de
            JOIN highlights h ON h.id = de.highlight_id
            JOIN conversations c ON c.id = h.conversation_id
            LEFT JOIN companies co ON co.id = c.company_id
            """
        )
    ).mappings().all()
    for r in rows:
        conn.execute(
            sa.text(
                """
                UPDATE decision_evidence
                SET quote_snapshot = :quote,
                    company_name = :company_name,
                    conversation_id = :conv_id,
                    conversation_date = :happened_at
                WHERE id = :ev_id
                """
            ),
            {
                "quote": r["quote"],
                "company_name": r["company_name"],
                "conv_id": r["conv_id"],
                "happened_at": r["happened_at"],
                "ev_id": r["ev_id"],
            },
        )


def downgrade() -> None:
    with op.batch_alter_table("decision_evidence") as batch_op:
        batch_op.alter_column("highlight_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_column("invalid_reason")
        batch_op.drop_column("cited_at")
        batch_op.drop_column("conversation_date")
        batch_op.drop_column("conversation_id")
        batch_op.drop_column("company_name")
        batch_op.drop_column("quote_snapshot")
    with op.batch_alter_table("decisions") as batch_op:
        batch_op.drop_column("integrity_checked_at")
