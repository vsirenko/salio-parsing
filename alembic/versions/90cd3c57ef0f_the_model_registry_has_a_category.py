"""the model registry has a category

A maker's names for its phones are not its names for its tablets. Keyed by brand alone, the
registry read Nubia's phone `Air` into `Apple iPad Air`, and 130 of m79's tablets would have
been filed under it. Each row now belongs to one category, and a category reads its own.

Every row there is was seeded from phone listings and entered for phones, so every row goes
to `phones`. A database whose registry holds rows and no `phones` category has rows this
cannot place, and the NOT NULL fails on them rather than guessing a category.

Revision ID: 90cd3c57ef0f
Revises: b8e1f4c27d93
Create Date: 2026-09-23 12:19:14.385972
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "90cd3c57ef0f"
down_revision: str | Sequence[str] | None = "b8e1f4c27d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_aliases", sa.Column("category_id", sa.Integer(), nullable=True))
    op.execute(
        "update model_aliases set category_id = (select id from categories where slug = 'phones')"
    )
    op.alter_column("model_aliases", "category_id", nullable=False)
    op.drop_constraint("uq_model_alias_per_brand", "model_aliases", type_="unique")
    op.create_unique_constraint(
        "uq_model_alias_per_category",
        "model_aliases",
        ["category_id", "brand_id", "alias_normalized"],
    )
    op.create_foreign_key(
        "fk_model_aliases_category_id_categories",
        "model_aliases",
        "categories",
        ["category_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # One spelling may now be a model in two categories; the old key would refuse the second,
    # so only one row per brand and spelling survives the way back.
    op.execute(
        """
        delete from model_aliases a using model_aliases b
        where a.brand_id = b.brand_id and a.alias_normalized = b.alias_normalized
          and a.id > b.id
        """
    )
    op.drop_constraint("fk_model_aliases_category_id_categories", "model_aliases", type_="foreignkey")
    op.drop_constraint("uq_model_alias_per_category", "model_aliases", type_="unique")
    op.create_unique_constraint(
        "uq_model_alias_per_brand", "model_aliases", ["brand_id", "alias_normalized"]
    )
    op.drop_column("model_aliases", "category_id")
