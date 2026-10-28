"""users and the default admin

The default admin (login: admin, password: admin) is for development only.
Change the password before any real deployment.
"""

import sqlalchemy as sa

from alembic import op
from app.core.security import hash_password

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    users = op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("username", sa.String(32), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(64)),
        sa.Column("bio", sa.Text()),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)
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
    op.drop_table("users")
