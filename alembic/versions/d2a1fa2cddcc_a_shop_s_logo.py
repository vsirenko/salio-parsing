"""a shop's logo

Where a shop's logo is, for the admin panel's list and a storefront to show it by: a URL,
not a stored file — the shop hosts its own, and a copy would go stale when it rebrands.

Revision ID: d2a1fa2cddcc
Revises: 261a9e920080
Create Date: 2026-09-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2a1fa2cddcc"
down_revision: str | Sequence[str] | None = "261a9e920080"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shops", sa.Column("logo_url", sa.String(length=1000), nullable=True))


def downgrade() -> None:
    op.drop_column("shops", "logo_url")
