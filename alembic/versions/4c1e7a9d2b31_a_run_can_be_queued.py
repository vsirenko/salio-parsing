"""a run can be queued

A run started from the panel was created `running` with nothing behind it: the scheduler
spawns workers for what is due, and a row nobody scheduled is not due. It sat until the next
startup swept it. It is `queued` now, and the scheduler's next tick gives it a worker.

Live is either state, so the check that ties `finished_at` to the status widens to both, and
the one-live-run-per-channel index — on `finished_at is null` — already covers a queued one.

Revision ID: 4c1e7a9d2b31
Revises: ffaf12b0d3b0
Create Date: 2026-09-24 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4c1e7a9d2b31"
down_revision: str | Sequence[str] | None = "ffaf12b0d3b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(op.f("ck_runs_status_known"), "runs", type_="check")
    op.drop_constraint(op.f("ck_runs_finished_matches_status"), "runs", type_="check")
    op.create_check_constraint(
        op.f("ck_runs_status_known"),
        "runs",
        "status in ('queued', 'running', 'ok', 'rejected', 'failed', 'interrupted')",
    )
    op.create_check_constraint(
        op.f("ck_runs_finished_matches_status"),
        "runs",
        "(status in ('queued', 'running')) = (finished_at is null)",
    )


def downgrade() -> None:
    # A queued run has no worker and never had one: it goes back as interrupted.
    op.execute(
        "update runs set status = 'interrupted', finished_at = now() where status = 'queued'"
    )
    op.drop_constraint(op.f("ck_runs_finished_matches_status"), "runs", type_="check")
    op.drop_constraint(op.f("ck_runs_status_known"), "runs", type_="check")
    op.create_check_constraint(
        op.f("ck_runs_status_known"),
        "runs",
        "status in ('running', 'ok', 'rejected', 'failed', 'interrupted')",
    )
    op.create_check_constraint(
        op.f("ck_runs_finished_matches_status"),
        "runs",
        "(status = 'running') = (finished_at is null)",
    )
