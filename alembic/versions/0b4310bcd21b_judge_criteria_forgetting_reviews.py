"""judge criteria, forgetting and reviews

What each option was described as when it was asked — kept from now on; the answers bought
before carry none. An answer can be forgotten, which stops the store answering with it and
keeps what it cost counted, so the one live answer per question becomes a partial unique
index. And a person's word on an answer, which a confidence threshold is measured against.

Revision ID: 0b4310bcd21b
Revises: 37880b3b6cee
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0b4310bcd21b"
down_revision: str | Sequence[str] | None = "37880b3b6cee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "judge_reviews",
        sa.Column("verdict_id", sa.Integer(), nullable=False),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.id"],
            name=op.f("fk_judge_reviews_reviewed_by_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["verdict_id"],
            ["judge_verdicts.id"],
            name=op.f("fk_judge_reviews_verdict_id_judge_verdicts"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("verdict_id", name=op.f("pk_judge_reviews")),
    )
    op.add_column(
        "judge_verdicts",
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "judge_verdicts", sa.Column("forgotten_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_constraint(op.f("uq_judge_verdicts_question_hash"), "judge_verdicts", type_="unique")
    op.create_index(
        "uq_judge_verdicts_question_hash",
        "judge_verdicts",
        ["question_hash"],
        unique=True,
        postgresql_where=sa.text("forgotten_at is null"),
    )


def downgrade() -> None:
    # A forgotten answer beside the one that replaced it cannot stand under a plain unique
    # constraint, and it answers nothing.
    op.execute("delete from judge_verdicts where forgotten_at is not null")
    op.drop_index("uq_judge_verdicts_question_hash", table_name="judge_verdicts")
    op.create_unique_constraint(
        op.f("uq_judge_verdicts_question_hash"), "judge_verdicts", ["question_hash"]
    )
    op.drop_column("judge_verdicts", "forgotten_at")
    op.drop_column("judge_verdicts", "criteria")
    op.drop_table("judge_reviews")
