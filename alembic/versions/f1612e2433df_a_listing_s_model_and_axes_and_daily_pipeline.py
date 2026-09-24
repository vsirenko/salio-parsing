"""a listing's model and axes, and the pipeline kept daily

`offers.model` and `offers.identity`, copied from the newest reading of a pass that carried
the catalogue as the title and barcode already are, so "read, without its colour" is a filter
over listings. Filled here from the readings stored. And `pipeline_snapshots`: the pipeline's
key numbers per day, which cannot be recomputed later because everything else is counted as
it is now.

Revision ID: f1612e2433df
Revises: 88667bdd8dd5
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1612e2433df"
down_revision: str | Sequence[str] | None = "88667bdd8dd5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_snapshots",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "taken_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("day", "scope", name=op.f("pk_pipeline_snapshots")),
    )
    op.add_column("offers", sa.Column("model", sa.String(length=200), nullable=True))
    op.add_column(
        "offers",
        sa.Column(
            "identity",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )
    # The same reading `title` was filled from: the newest of a pass that carried the
    # catalogue, a sample loaded by hand counting as one.
    op.execute(
        """
        update offers o
           set model = r.model, identity = coalesce(r.identity, '{}'::jsonb)
          from (
            select distinct on (ro.offer_id) ro.offer_id, n.model, n.identity
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
    op.drop_column("offers", "identity")
    op.drop_column("offers", "model")
    op.drop_table("pipeline_snapshots")
