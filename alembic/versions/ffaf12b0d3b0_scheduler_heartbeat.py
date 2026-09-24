"""scheduler heartbeat

One row the scheduler rewrites on every tick. `runs` says when each channel last ran and
what is running; with nothing due it says nothing, and on 23.09.2026 that looked exactly
like a scheduler that had stopped. A stale `ticked_at` is the answer to that question.

Revision ID: ffaf12b0d3b0
Revises: 90cd3c57ef0f
Create Date: 2026-09-24 08:06:46.027862
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ffaf12b0d3b0"
down_revision: str | Sequence[str] | None = "90cd3c57ef0f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_heartbeat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ticked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pid", sa.Integer(), nullable=False),
        sa.Column("running", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_last_tick", sa.Integer(), server_default="0", nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_scheduler_heartbeat_one_row")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_scheduler_heartbeat")),
    )


def downgrade() -> None:
    op.drop_table("scheduler_heartbeat")
