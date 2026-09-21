"""split brand_unresolved into unknown and ambiguous

Revision ID: 494571d7c41f
Revises: 661f69288bd6
Create Date: 2026-09-21 19:15:26.967623

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '494571d7c41f'
down_revision: Union[str, Sequence[str], None] = '661f69288bd6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The literal name. It is passed through op.f() at the call sites rather than here: the
# proxy is not established while the module is merely imported, which is what `alembic
# revision` does to every file in the directory.
CONSTRAINT = "ck_match_queue_reason_known"


def upgrade() -> None:
    """Upgrade schema.

    One reason covered two problems that are finished in different ways. A string that
    resolves to no brand has to be researched — someone reads the raw value and decides
    what it is. A string that resolves to two has its answers already in hand and only has
    to be chosen between, which is a click rather than a search. Counting them together
    made the queue summary say "brand aliases" without saying how much of that work is
    looking things up, and that is the number the next step is chosen on.

    Existing rows collapse into `brand_unknown`: it is the bucket that means "go and look",
    so a row landing there is at worst more work than it needed, never a wrong answer. The
    matcher rewrites the reason on its next pass over that offer anyway.
    """
    op.drop_constraint(op.f(CONSTRAINT), "match_queue", type_="check")
    op.execute("update match_queue set reason = 'brand_unknown' where reason = 'brand_unresolved'")
    op.create_check_constraint(
        op.f(CONSTRAINT),
        "match_queue",
        "reason in ('brand_unknown', 'brand_ambiguous', 'no_signals',"
        " 'signals_unmatched', 'ambiguous', 'low_confidence')",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f(CONSTRAINT), "match_queue", type_="check")
    op.execute(
        "update match_queue set reason = 'brand_unresolved'"
        " where reason in ('brand_unknown', 'brand_ambiguous')"
    )
    op.create_check_constraint(
        op.f(CONSTRAINT),
        "match_queue",
        "reason in ('brand_unresolved', 'no_signals', 'signals_unmatched',"
        " 'ambiguous', 'low_confidence')",
    )
