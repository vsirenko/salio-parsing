"""let an account collect without being an administrator

Revision ID: 4d51a1201c3c
Revises: cf9b06ccd277
Create Date: 2026-09-21 21:02:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '4d51a1201c3c'
down_revision: Union[str, Sequence[str], None] = 'cf9b06ccd277'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

CONSTRAINT = "ck_users_role_known"


def upgrade() -> None:
    """Upgrade schema.

    A collector needs to hand over what it crawled and say how the run went, and nothing
    else. Doing that with an administrator's credentials would give a parser — the one
    thing here that runs hostile input through itself all day — the ability to do anything
    an administrator can, including deleting accounts.

    The role is only half of it. The boundary is the token audience, as it already is
    between the two panels: a worker token carries `aud=worker` and is refused by the
    admin panel before any role check runs.
    """
    op.drop_constraint(op.f(CONSTRAINT), "users", type_="check")
    op.create_check_constraint(
        op.f(CONSTRAINT), "users", "role in ('customer', 'admin', 'worker')"
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Machine accounts have no place in the older vocabulary; they are retired rather than
    # deleted, for the same reason no account is ever deleted.
    op.execute("update users set is_active = false where role = 'worker'")
    op.execute("update users set role = 'customer' where role = 'worker'")
    op.drop_constraint(op.f(CONSTRAINT), "users", type_="check")
    op.create_check_constraint(op.f(CONSTRAINT), "users", "role in ('customer', 'admin')")
