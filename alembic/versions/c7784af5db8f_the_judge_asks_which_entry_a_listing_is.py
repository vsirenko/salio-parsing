"""the judge asks which entry a listing is

A second question kind. The first was `brand_choice`, for a string that means two
companies; this one is `variant_choice`, for a listing that reaches the model rung and
finds several catalogue entries differing in one axis and agreeing on every other.

Autogenerate does not see a check constraint change, so this is written by hand: the
constraint is dropped and rebuilt with the new value beside the old one.

Revision ID: c7784af5db8f
Revises: 222092b703c9
Create Date: 2026-09-22 13:52:03.299606
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7784af5db8f"
down_revision: str | Sequence[str] | None = "222092b703c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The naming convention adds the `ck_<table>_` prefix, so this is the bare name.
CONSTRAINT = "kind_known"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "judge_verdicts", type_="check")
    op.create_check_constraint(
        "kind_known", "judge_verdicts", "kind in ('brand_choice', 'variant_choice')"
    )


def downgrade() -> None:
    # Answers to the new question would fail the old constraint, so they go first. They are
    # bought answers and deleting them costs money to replace — which is the point of
    # noticing here rather than finding out when the constraint refuses to build.
    op.execute("delete from judge_verdicts where kind = 'variant_choice'")
    op.drop_constraint(CONSTRAINT, "judge_verdicts", type_="check")
    op.create_check_constraint("kind_known", "judge_verdicts", "kind in ('brand_choice')")
