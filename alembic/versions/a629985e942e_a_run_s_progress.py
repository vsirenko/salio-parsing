"""a run's progress

What a run has done so far, while it does it: the worker's counts as it reads and hands
over, then what settling it placed. `items_*` are the verdict at the end; this is how one
run is watched filling in, step by step.

Revision ID: a629985e942e
Revises: 4c1e7a9d2b31
Create Date: 2026-09-24 09:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "a629985e942e"
down_revision: str | Sequence[str] | None = "4c1e7a9d2b31"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "progress", postgresql.JSONB(astext_type=sa.Text()), server_default="{}", nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("runs", "progress")
