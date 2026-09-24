"""values an attribute deliberately does not have

A word a shop writes for an attribute that is not one of its values — `melna, pelēka` in a
colour field is two colours — marked so the list of what the registry does not know stops
showing it. The list itself is computed from the readings and stores nothing else.

Revision ID: de6ddf420633
Revises: 0b4310bcd21b
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "de6ddf420633"
down_revision: str | Sequence[str] | None = "0b4310bcd21b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attribute_value_dismissals",
        sa.Column("attribute_id", sa.Integer(), nullable=False),
        sa.Column("value_normalized", sa.String(length=200), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("dismissed_by", sa.Integer(), nullable=True),
        sa.Column(
            "dismissed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["attribute_id"],
            ["attributes.id"],
            name=op.f("fk_attribute_value_dismissals_attribute_id_attributes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dismissed_by"],
            ["users.id"],
            name=op.f("fk_attribute_value_dismissals_dismissed_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "attribute_id", "value_normalized", name=op.f("pk_attribute_value_dismissals")
        ),
    )


def downgrade() -> None:
    op.drop_table("attribute_value_dismissals")
