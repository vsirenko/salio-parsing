"""a run can be cancelled, and names its failures

`cancelled`: a person stopped it — queued or running — from the panel, which used to be
possible only by restarting the scheduler. And a sample of the products that did not make
it, each with its stage and reason, where there was only a count.

Revision ID: 88667bdd8dd5
Revises: de6ddf420633
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "88667bdd8dd5"
down_revision: str | Sequence[str] | None = "de6ddf420633"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KNOWN = "'queued', 'running', 'ok', 'rejected', 'failed', 'interrupted'"


def upgrade() -> None:
    op.add_column(
        "runs",
        sa.Column(
            "failures",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
    )
    op.drop_constraint(op.f("ck_runs_status_known"), "runs", type_="check")
    op.create_check_constraint(
        op.f("ck_runs_status_known"), "runs", f"status in ({KNOWN}, 'cancelled')"
    )


def downgrade() -> None:
    # A cancelled run was stopped by a person; the nearest older word is `interrupted`.
    op.execute("update runs set status = 'interrupted' where status = 'cancelled'")
    op.drop_constraint(op.f("ck_runs_status_known"), "runs", type_="check")
    op.create_check_constraint(op.f("ck_runs_status_known"), "runs", f"status in ({KNOWN})")
    op.drop_column("runs", "failures")
