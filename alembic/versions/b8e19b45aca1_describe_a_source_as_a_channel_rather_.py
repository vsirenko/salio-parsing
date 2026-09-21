"""describe a source as a channel rather than a format

Revision ID: b8e19b45aca1
Revises: 3497f9892c8a
Create Date: 2026-09-21 20:04:11.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8e19b45aca1'
down_revision: Union[str, Sequence[str], None] = '3497f9892c8a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FACTS = "array['catalogue', 'price', 'availability']::text[]"


def upgrade() -> None:
    """Upgrade schema.

    `kind` recorded a format — feed, api, scrape — and format is the part of a channel
    that matters least: it decides how a response is decoded and nothing else. What
    actually shapes the work is how many requests a product costs and which facts each
    request brings back, and `api` sat astride both answers.

    The three columns that replace it are the channel's declaration. `access` decides the
    schedule. `decode` is a swappable function. `delivers_*` is the one that is easy to get
    wrong and expensive to discover: whether a cheap pass carries stock is a property of
    the channel, not a general rule, and it decides whether fresh availability costs a full
    crawl.
    """
    op.add_column("sources", sa.Column("access", sa.String(length=10), nullable=True))
    op.add_column("sources", sa.Column("decode", sa.String(length=20), nullable=True))
    op.add_column(
        "sources", sa.Column("delivers_full", sa.ARRAY(sa.Text()), nullable=True)
    )
    op.add_column(
        "sources",
        sa.Column(
            "delivers_quick", sa.ARRAY(sa.Text()), server_default="{}", nullable=True
        ),
    )

    # A best guess, and deliberately a conservative one: every existing row is assumed to
    # deliver nothing cheaply. A channel wrongly believed to have a quick pass would have
    # partial observations scheduled against it four times a day; one wrongly believed to
    # have none is only crawled more than it needs to be. The rows are development data
    # and each one is meant to be restated by hand.
    op.execute(
        f"""
        update sources set
            access = case when kind = 'feed' then 'wholesale' else 'retail' end,
            decode = case kind when 'feed' then 'xml'
                               when 'api'  then 'private_api'
                               else 'markup' end,
            delivers_full = {FACTS},
            delivers_quick = '{{}}'::text[]
        """
    )

    for column in ("access", "decode", "delivers_full", "delivers_quick"):
        op.alter_column("sources", column, nullable=False)

    op.drop_constraint(op.f("ck_sources_kind_known"), "sources", type_="check")
    op.drop_column("sources", "kind")

    op.create_check_constraint(
        op.f("ck_sources_access_known"), "sources", "access in ('wholesale', 'retail')"
    )
    op.create_check_constraint(
        op.f("ck_sources_decode_known"),
        "sources",
        "decode in ('json_ld', 'embedded_state', 'graphql', 'private_api', 'xml', 'markup')",
    )
    op.create_check_constraint(
        op.f("ck_sources_delivers_full_known"),
        "sources",
        f"delivers_full <@ {FACTS} and cardinality(delivers_full) > 0",
    )
    op.create_check_constraint(
        op.f("ck_sources_quick_within_full"), "sources", "delivers_quick <@ delivers_full"
    )
    op.create_check_constraint(
        op.f("ck_sources_wholesale_has_no_quick_pass"),
        "sources",
        "access <> 'wholesale' or cardinality(delivers_quick) = 0",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("sources", sa.Column("kind", sa.String(length=10), nullable=True))
    op.execute(
        """
        update sources set kind = case when access = 'wholesale' then 'feed'
                                       when decode in ('private_api', 'graphql') then 'api'
                                       else 'scrape' end
        """
    )
    op.alter_column("sources", "kind", nullable=False)
    op.create_check_constraint(
        op.f("ck_sources_kind_known"), "sources", "kind in ('feed', 'api', 'scrape')"
    )

    for name in (
        "ck_sources_wholesale_has_no_quick_pass",
        "ck_sources_quick_within_full",
        "ck_sources_delivers_full_known",
        "ck_sources_decode_known",
        "ck_sources_access_known",
    ):
        op.drop_constraint(op.f(name), "sources", type_="check")
    for column in ("delivers_quick", "delivers_full", "decode", "access"):
        op.drop_column("sources", column)
