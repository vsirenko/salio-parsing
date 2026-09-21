"""let a parser be re-run over the bytes already held

Revision ID: f41f3175ce67
Revises: 4d51a1201c3c
Create Date: 2026-09-21 21:40:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = 'f41f3175ce67'
down_revision: Union[str, Sequence[str], None] = '4d51a1201c3c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_runs_kind_known"


def upgrade() -> None:
    """Upgrade schema.

    A parser is wrong more often than a site changes, and until now a fix could only be
    judged by crawling the shop again — which is slow, rude to the shop, and measures the
    site as it is today rather than as it was when the parser broke.

    `reparse` reads the snapshots already on the worker's disk with the parser as it is
    now. It has no cron and is never due: the scheduler only knows about the two kinds with
    a schedule, so this one is started by hand, which is also when it is wanted.

    It must never earn the absence inference. A reparse sees whatever happens to be in the
    snapshot store, which is a subset by construction, so what it did not see means
    nothing — only a collecting run that ended `ok` may conclude a product is gone.
    """
    op.drop_constraint(op.f(CONSTRAINT), "runs", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), "runs", "kind in ('full', 'quick', 'reparse')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Reparse runs are history rather than state; dropping them loses the record of which
    # parser fix helped, which is the only reason they were kept.
    op.execute("delete from runs where kind = 'reparse'")
    op.drop_constraint(op.f(CONSTRAINT), "runs", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "runs", "kind in ('full', 'quick')")
