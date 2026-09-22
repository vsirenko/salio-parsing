"""a queue reason nobody can settle

`ambiguous` promised a choice somebody could make. For 52 of its 58 rows nobody could: the
shop publishes the model, the memory and the screen and never the colour, and the catalogue
holds that phone in three colours. The judge was asked about every one of them and refused
30 of 30, correctly.

Autogenerate does not see a check constraint change, so this is written by hand.

Revision ID: e4c2b81a7f56
Revises: d3a91c6e0f47
Create Date: 2026-09-22 19:05:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4c2b81a7f56"
down_revision: str | Sequence[str] | None = "d3a91c6e0f47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The naming convention adds the `ck_<table>_` prefix, so this is the bare name.
CONSTRAINT = "reason_known"
OLD = (
    "'brand_unknown', 'brand_ambiguous', 'no_signals', 'signals_unmatched',"
    " 'ambiguous', 'low_confidence'"
)
NEW = f"{OLD}, 'axis_unpublished'"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "match_queue", type_="check")
    op.create_check_constraint(CONSTRAINT, "match_queue", f"reason in ({NEW})")


def downgrade() -> None:
    # A row carrying the new reason would fail the old constraint. It is a queue entry and
    # the matcher rebuilds it on the next pass, so it goes back to the bucket it came from
    # rather than being deleted.
    op.execute("update match_queue set reason = 'ambiguous' where reason = 'axis_unpublished'")
    op.drop_constraint(CONSTRAINT, "match_queue", type_="check")
    op.create_check_constraint(CONSTRAINT, "match_queue", f"reason in ({OLD})")
