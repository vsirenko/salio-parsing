"""the judge checks a match

The fourth question kind, and the first that questions a decision instead of making one:
`model_match` asks whether a listing sells the model its entry is named. Both of the
silent misfilings found on 22.09.2026 — `Galaxy S26+` under the plain phone, `iPhone 16 Pro`
under `iPhone 16` — were a rule agreeing with a reading that was wrong, and this is the
check that saw both.

Autogenerate does not see a check constraint change, so this is written by hand.

Revision ID: a6c2e9d41b07
Revises: 87be04a227a1
Create Date: 2026-09-23 08:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a6c2e9d41b07"
down_revision: str | Sequence[str] | None = "87be04a227a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The naming convention adds the `ck_<table>_` prefix, so this is the bare name.
CONSTRAINT = "kind_known"
KINDS = "('brand_choice', 'variant_choice', 'colour_choice', 'model_match')"


def upgrade() -> None:
    op.drop_constraint(CONSTRAINT, "judge_verdicts", type_="check")
    op.create_check_constraint(CONSTRAINT, "judge_verdicts", f"kind in {KINDS}")


def downgrade() -> None:
    # Answers to the new question would fail the old constraint, so they go first. They are
    # bought answers and deleting them costs money to replace.
    op.execute("delete from judge_verdicts where kind = 'model_match'")
    op.drop_constraint(CONSTRAINT, "judge_verdicts", type_="check")
    op.create_check_constraint(
        CONSTRAINT,
        "judge_verdicts",
        "kind in ('brand_choice', 'variant_choice', 'colour_choice')",
    )
