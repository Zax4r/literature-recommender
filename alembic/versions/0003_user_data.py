"""favorites, library, tags with votes, recommendation history"""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("book_id", sa.BigInteger(), sa.ForeignKey("books.id", ondelete="CASCADE")),
        sa.PrimaryKeyConstraint("user_id", "book_id"),
    )
    op.create_table(
        "user_books",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("book_id", sa.BigInteger(), sa.ForeignKey("books.id", ondelete="CASCADE")),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rating", sa.SmallInteger()),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("user_id", "book_id"),
    )
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
    )
    op.create_index("ix_tags_name", "tags", ["name"], unique=True)
    op.create_table(
        "book_tags",
        sa.Column("book_id", sa.BigInteger(), sa.ForeignKey("books.id", ondelete="CASCADE")),
        sa.Column("tag_id", sa.Integer(), sa.ForeignKey("tags.id", ondelete="CASCADE")),
        sa.Column("weight", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("book_id", "tag_id"),
    )
    op.create_table(
        "tag_votes",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("book_id", sa.BigInteger()),
        sa.Column("tag_id", sa.Integer()),
        sa.Column("value", sa.SmallInteger(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "book_id", "tag_id"),
        sa.ForeignKeyConstraint(
            ["book_id", "tag_id"], ["book_tags.book_id", "book_tags.tag_id"], ondelete="CASCADE"
        ),
    )
    op.create_table(
        "recommendations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("query", sa.Text(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_recommendations_user_id", "recommendations", ["user_id"])
    op.create_table(
        "recommendation_items",
        sa.Column(
            "recommendation_id",
            sa.Integer(),
            sa.ForeignKey("recommendations.id", ondelete="CASCADE"),
        ),
        sa.Column("book_id", sa.BigInteger(), sa.ForeignKey("books.id", ondelete="CASCADE")),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("stores", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("recommendation_id", "book_id"),
    )


def downgrade() -> None:
    for table in (
        "recommendation_items",
        "recommendations",
        "tag_votes",
        "book_tags",
        "tags",
        "user_books",
        "favorites",
    ):
        op.drop_table(table)
