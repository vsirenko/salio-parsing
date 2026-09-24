"""labels for attributes and their values

What a person reads, by language, beside the name the registry is kept in: an attribute is
`Working memory` in the registry and `Operatīvā atmiņa` or `Оперативная память` on a page,
a value is `black` to the matcher and `melns` to a buyer. The category's `label_override`
was one string for every language. Empty by default: a label nobody wrote falls back to the
name.

Revision ID: 261a9e920080
Revises: 9345e5a7389c
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "261a9e920080"
down_revision: str | Sequence[str] | None = "9345e5a7389c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for table in ("attributes", "attribute_values"):
        op.add_column(
            table,
            sa.Column(
                "labels",
                postgresql.JSONB(astext_type=sa.Text()),
                server_default="{}",
                nullable=False,
            ),
        )


def downgrade() -> None:
    for table in ("attribute_values", "attributes"):
        op.drop_column(table, "labels")
