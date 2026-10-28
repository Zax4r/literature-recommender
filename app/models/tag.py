from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, ForeignKeyConstraint, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.book import Book


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True, index=True)


class BookTag(Base):
    """A tag on a book. `weight` is the shelf count from the UCSD dataset (0 for user-added)."""

    __tablename__ = "book_tags"

    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
    weight: Mapped[int] = mapped_column(default=0)

    book: Mapped["Book"] = relationship()
    tag: Mapped[Tag] = relationship()


class TagVote(Base):
    __tablename__ = "tag_votes"
    __table_args__ = (
        ForeignKeyConstraint(
            ["book_id", "tag_id"], ["book_tags.book_id", "book_tags.tag_id"], ondelete="CASCADE"
        ),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    book_id: Mapped[int] = mapped_column(primary_key=True)
    tag_id: Mapped[int] = mapped_column(primary_key=True)
    value: Mapped[int] = mapped_column(SmallInteger)
