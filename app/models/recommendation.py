from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    query: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(16))
    answer: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    items: Mapped[list["RecommendationItem"]] = relationship(
        order_by="RecommendationItem.position", lazy="selectin"
    )


class RecommendationItem(Base):
    __tablename__ = "recommendation_items"

    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE"), primary_key=True
    )
    book_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("books.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int]
    reason: Mapped[str] = mapped_column(Text)
    stores: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
