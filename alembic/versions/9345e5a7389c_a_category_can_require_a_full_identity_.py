"""a category can require a full identity on the model rung

A model string names a family. For a phone that family is a handful of capacities and
colours, and the model rung placing a listing on the one entry that agrees with it on the
axes both carry is usually right. For a laptop it is dozens of configurations: on bigbox's
first laptop run, 24.09.2026, 234 of 392 model matches were made on an incomplete identity,
and a ThinkBook whose chip was not read was placed on the one with `7 240H`. The flag is off
for every existing category, which keeps their behaviour.

Revision ID: 9345e5a7389c
Revises: a629985e942e
Create Date: 2026-09-24 10:39:24.700593
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9345e5a7389c"
down_revision: str | Sequence[str] | None = "a629985e942e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "categories",
        sa.Column(
            "model_match_needs_full_identity",
            sa.Boolean(),
            server_default="false",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("categories", "model_match_needs_full_identity")
