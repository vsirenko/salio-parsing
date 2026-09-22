"""the judge names a colour

The third question kind. `variant_choice` refused thirty listings of thirty and was right
to: at confidence 1.00 a `Coralred` Samsung is neither of the entries the catalogue holds.
They do not need matching, they need an entry of their own, and what blocks that is the
colour nobody can read. `colour_choice` is what unblocks it.

Autogenerate does not see a check constraint change, so this is written by hand.

Revision ID: d3a91c6e0f47
Revises: c7784af5db8f
Create Date: 2026-09-22 14:05:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d3a91c6e0f47"
down_revision: str | Sequence[str] | None = "c7784af5db8f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The naming convention adds the `ck_<table>_` prefix, so this is the bare name.
CONSTRAINT = "kind_known"
KINDS = "('brand_choice', 'variant_choice', 'colour_choice')"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "judge_verdicts", type_="check")
    op.create_check_constraint(CONSTRAINT, "judge_verdicts", f"kind in {KINDS}")


def downgrade() -> None:
    # Answers to the new question would fail the old constraint, so they go first. They are
    # bought answers and deleting them costs money to replace.
    op.execute("delete from judge_verdicts where kind = 'colour_choice'")
    op.drop_constraint(CONSTRAINT, "judge_verdicts", type_="check")
    op.create_check_constraint(
        CONSTRAINT, "judge_verdicts", "kind in ('brand_choice', 'variant_choice')"
    )
