from datetime import datetime

from sqlalchemy import ARRAY, JSON, BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Postgres uses a native text[]; SQLite (tests) falls back to JSON.
TextArray = ARRAY(Text).with_variant(JSON(), "sqlite")
# SQLite only autoincrements INTEGER primary keys.
BigId = BigInteger().with_variant(Integer(), "sqlite")


class Book(Base):
    """A catalog card from the data pipeline; `source_idx` is the key shared with Qdrant."""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(BigId, primary_key=True, autoincrement=True)
    source_idx: Mapped[int] = mapped_column(unique=True)
    title: Mapped[str] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text)
    genres: Mapped[list[str]] = mapped_column(TextArray, default=list)
    tropes: Mapped[list[str]] = mapped_column(TextArray, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Favorite(Base):
    __tablename__ = "favorites"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
