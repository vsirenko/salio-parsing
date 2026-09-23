"""one barcode, one form

Every stored barcode becomes a GTIN-14, zero-padded. A UPC-A and the EAN-13 it becomes with
a leading zero are one code — `840493610849` and `0840493610849` are one Motorola — and 229
of 2736 distinct codes in the readings, 223 of them on catalogue entries, were stored both
ways, so the barcode rung missed between exactly the shops that wrote them differently.

An entry holding both forms of one code keeps one row, a person's before a rule's. The
readings are rewritten as well: the matcher looks a listing up by its newest reading, and a
reading older than the reparse that follows would otherwise still carry the short form.

Revision ID: b8e1f4c27d93
Revises: a6c2e9d41b07
Create Date: 2026-09-23 09:00:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8e1f4c27d93"
down_revision: str | Sequence[str] | None = "a6c2e9d41b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "gtin_digits"


def upgrade() -> None:
    # Two forms of one code on one entry would collide on the primary key once padded.
    # Keep the row a person entered over one a rule learned, then the oldest.
    op.execute(
        """
        delete from variant_gtins g
        using (
            select variant_id, gtin,
                   row_number() over (
                       partition by variant_id, lpad(gtin, 14, '0')
                       order by (origin = 'human') desc, first_seen_at, gtin
                   ) as rank
            from variant_gtins
        ) ranked
        where g.variant_id = ranked.variant_id and g.gtin = ranked.gtin and ranked.rank > 1
        """
    )
    op.drop_constraint(CONSTRAINT, "variant_gtins", type_="check")
    op.execute("update variant_gtins set gtin = lpad(gtin, 14, '0') where length(gtin) < 14")
    op.create_check_constraint(CONSTRAINT, "variant_gtins", "gtin ~ '^[0-9]{14}$'")
    op.execute(
        "update normalized_offers set gtin = lpad(gtin, 14, '0')"
        " where gtin is not null and length(gtin) < 14"
    )


def downgrade() -> None:
    # The padding cannot be undone exactly — `00840493610849` was written as twelve digits
    # by one shop and thirteen by another — so the codes stay padded, which the old
    # constraint accepts. Only the constraint goes back.
    op.drop_constraint(CONSTRAINT, "variant_gtins", type_="check")
    op.create_check_constraint(CONSTRAINT, "variant_gtins", "gtin ~ '^[0-9]{8,14}$'")
