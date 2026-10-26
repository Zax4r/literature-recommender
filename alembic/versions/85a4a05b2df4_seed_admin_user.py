"""seed admin user

Revision ID: 85a4a05b2df4
Revises: 52c79e2a0cb6
Create Date: 2026-10-27 00:19:21.689165

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.core.security import hash_password


# revision identifiers, used by Alembic.
revision: str = "85a4a05b2df4"
down_revision: Union[str, Sequence[str], None] = "52c79e2a0cb6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the default admin (login: admin, password: admin). Change it outside development."""
    users = sa.table(
        "users",
        sa.column("email", sa.String),
        sa.column("username", sa.String),
        sa.column("hashed_password", sa.String),
        sa.column("is_admin", sa.Boolean),
    )
    op.bulk_insert(
        users,
        [
            {
                "email": "admin@example.com",
                "username": "admin",
                "hashed_password": hash_password("admin"),
                "is_admin": True,
            }
        ],
    )


def downgrade() -> None:
    op.execute("DELETE FROM users WHERE username = 'admin'")
