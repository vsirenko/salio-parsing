"""the brand and model a queue row names

The brand the matcher settled on and the model it searched for, on the row that says it
failed: the queue is read by maker, and grouped by what a single new entry would place.
Null on the rows already queued until the matcher next retries them, which every pass does
— the normalization is Python's, not SQL's, so a migration cannot fill it.

Revision ID: 37880b3b6cee
Revises: 137924c2ce57
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "37880b3b6cee"
down_revision: str | Sequence[str] | None = "137924c2ce57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("match_queue", sa.Column("brand_id", sa.Integer(), nullable=True))
    op.add_column("match_queue", sa.Column("model_key", sa.String(length=200), nullable=True))
    op.create_index(
        "ix_match_queue_brand_model", "match_queue", ["brand_id", "model_key"], unique=False
    )
    op.create_foreign_key(
        op.f("fk_match_queue_brand_id_brands"),
        "match_queue",
        "brands",
        ["brand_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_match_queue_brand_id_brands"), "match_queue", type_="foreignkey")
    op.drop_index("ix_match_queue_brand_model", table_name="match_queue")
    op.drop_column("match_queue", "model_key")
    op.drop_column("match_queue", "brand_id")
