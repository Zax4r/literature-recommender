"""Saving and presenting chat recommendations in the user's history."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Book, Recommendation, RecommendationItem, User
from app.schemas.recommendation import RecommendationItemOut, RecommendationOut, StoreLink
from app.services.books import to_list_items


def source_idx_to_book_id(db: Session, source_idxs: list[int]) -> dict[int, int]:
    if not source_idxs:
        return {}
    rows = db.execute(select(Book.source_idx, Book.id).where(Book.source_idx.in_(source_idxs)))
    return {r.source_idx: r.id for r in rows}


def save_recommendation(
    db: Session, user_id: int, query: str, source: str, answer: str, cards: list[dict[str, Any]]
) -> Recommendation:
    """Stores a chat answer; `cards` are the orchestrator's recommendations."""
    book_ids = source_idx_to_book_id(
        db, [c["source_idx"] for c in cards if c.get("source_idx") is not None]
    )
    recommendation = Recommendation(user_id=user_id, query=query, source=source, answer=answer)
    seen: set[int] = set()
    for card in cards:
        book_id = book_ids.get(card.get("source_idx"))  # type: ignore[arg-type]
        if book_id is None or book_id in seen:
            continue
        seen.add(book_id)
        recommendation.items.append(
            RecommendationItem(
                book_id=book_id,
                position=len(seen),
                reason=", ".join((card.get("tropes") or [])[:4]),
                stores=card.get("stores") or [],
            )
        )
    db.add(recommendation)
    db.commit()
    return recommendation


def to_out(db: Session, user: User, recommendation: Recommendation) -> RecommendationOut:
    books = {
        b.id: b
        for b in db.scalars(
            select(Book).where(Book.id.in_([i.book_id for i in recommendation.items]))
        )
    }
    ordered = [books[i.book_id] for i in recommendation.items]
    list_items = to_list_items(db, user, ordered)
    return RecommendationOut(
        id=recommendation.id,
        query=recommendation.query,
        source=recommendation.source,
        answer=recommendation.answer,
        created_at=recommendation.created_at,
        items=[
            RecommendationItemOut(
                book=list_item,
                reason=item.reason,
                stores=[StoreLink(**s) for s in item.stores],
            )
            for list_item, item in zip(list_items, recommendation.items, strict=True)
        ],
    )
