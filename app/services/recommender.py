"""Recommendation engine boundary.

The real engine is a separate AI service. Until it exists, `KeywordRecommender` stands in
for it: it matches words of the request against book titles and tags. To plug in the real
service, implement `Recommender` with an HTTP client and return it from `get_recommender`.
"""

import re
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Book, BookTag, Tag, UserBook

MAX_RESULTS = 5
UNWANTED_STATUSES = ("read", "reading", "dropped")


@dataclass(frozen=True)
class RecommendationRequest:
    text: str
    user_id: int


@dataclass(frozen=True)
class Recommended:
    book_id: int
    reason: str


class Recommender(Protocol):
    def recommend(self, request: RecommendationRequest) -> list[Recommended]: ...


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) >= 3}


class KeywordRecommender:
    def __init__(self, db: Session) -> None:
        self.db = db

    def recommend(self, request: RecommendationRequest) -> list[Recommended]:
        wanted = words(request.text)
        seen = set(
            self.db.scalars(
                select(UserBook.book_id).where(
                    UserBook.user_id == request.user_id, UserBook.status.in_(UNWANTED_STATUSES)
                )
            )
        )
        tags_by_book: dict[int, list[str]] = {}
        for book_id, name in self.db.execute(
            select(BookTag.book_id, Tag.name).join(Tag, Tag.id == BookTag.tag_id)
        ):
            tags_by_book.setdefault(book_id, []).append(name)

        scored: list[tuple[int, int, str]] = []
        for book in self.db.scalars(select(Book)):
            if book.id in seen:
                continue
            matched_tags = [t for t in tags_by_book.get(book.id, []) if words(t) & wanted]
            title_hits = words(book.title) & wanted
            score = 2 * len(matched_tags) + len(title_hits)
            if score:
                reason = "Совпадения: " + ", ".join([*matched_tags, *sorted(title_hits)])
                scored.append((score, book.id, reason))
        scored.sort(key=lambda s: (-s[0], s[1]))
        return [Recommended(book_id, reason) for _, book_id, reason in scored[:MAX_RESULTS]]
