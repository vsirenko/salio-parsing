"""what a listing was read as, on the listing

The title, brand string, barcode and category of the newest reading from a pass that
carried the catalogue, copied onto `offers` beside the price for the same reason: a list of
listings names and filters every row, and walking the observations for each one cost 0.4 s
a page. Filled here from the readings already stored; ingestion keeps it current.

Revision ID: 137924c2ce57
Revises: d2a1fa2cddcc
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "137924c2ce57"
down_revision: str | Sequence[str] | None = "d2a1fa2cddcc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("offers", sa.Column("title", sa.String(length=1000), nullable=True))
    op.add_column("offers", sa.Column("brand_raw", sa.String(length=200), nullable=True))
    op.add_column("offers", sa.Column("gtin", sa.String(length=14), nullable=True))
    op.add_column("offers", sa.Column("category_id", sa.Integer(), nullable=True))
    op.create_index("ix_offers_category_id", "offers", ["category_id"], unique=False)
    op.create_index("ix_offers_gtin", "offers", ["gtin"], unique=False)
    op.create_foreign_key(
        op.f("fk_offers_category_id_categories"), "offers", "categories", ["category_id"], ["id"]
    )
    # A reading of a quick pass has no title and would blank one; a reading with no run is
    # a sample loaded by hand, which is a full observation.
    op.execute(
        """
        update offers o
           set title = r.title, brand_raw = r.brand_raw, gtin = r.gtin,
               category_id = r.category_id
          from (
            select distinct on (ro.offer_id)
                   ro.offer_id, n.title, n.brand_raw, n.gtin, n.category_id
              from normalized_offers n
              join raw_offers ro on ro.id = n.raw_offer_id
              left join runs ru on ru.id = ro.run_id
             where ru.id is null or ru.kind <> 'quick'
             order by ro.offer_id, ro.fetched_at desc, ro.id desc, n.id desc
          ) r
         where r.offer_id = o.id
        """
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_offers_category_id_categories"), "offers", type_="foreignkey")
    op.drop_index("ix_offers_gtin", table_name="offers")
    op.drop_index("ix_offers_category_id", table_name="offers")
    op.drop_column("offers", "category_id")
    op.drop_column("offers", "gtin")
    op.drop_column("offers", "brand_raw")
    op.drop_column("offers", "title")
