from urllib.parse import quote_plus

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import Book, BookTag, Favorite, Tag, TagVote, User, UserBook
from app.schemas.book import BookListItem, TagOut

MAX_TAG_LENGTH = 100


def get_book_or_404(db: Session, book_id: int) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Book not found")
    return book


def normalize_tag_name(name: str) -> str:
    normalized = " ".join(name.lower().split())
    if not 2 <= len(normalized) <= MAX_TAG_LENGTH or not normalized.isprintable():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid tag name")
    return normalized


def store_url(book: Book) -> str:
    query = f"{book.title} {book.author}"
    return settings.STORE_SEARCH_URL.format(query=quote_plus(query))


def to_list_items(db: Session, user: User | None, books: list[Book]) -> list[BookListItem]:
    """Builds list items, filling in the user's favorite flag, status and rating."""
    favorites: set[int] = set()
    entries: dict[int, UserBook] = {}
    if user is not None and books:
        ids = [b.id for b in books]
        favorites = set(
            db.scalars(
                select(Favorite.book_id).where(
                    Favorite.user_id == user.id, Favorite.book_id.in_(ids)
                )
            )
        )
        entries = {
            e.book_id: e
            for e in db.scalars(
                select(UserBook).where(UserBook.user_id == user.id, UserBook.book_id.in_(ids))
            )
        }
    return [
        BookListItem(
            id=b.id,
            title=b.title,
            author=b.author,
            is_favorite=b.id in favorites,
            status=entries[b.id].status if b.id in entries else None,  # type: ignore[arg-type]
            rating=entries[b.id].rating if b.id in entries else None,
        )
        for b in books
    ]


def book_tags(db: Session, book_id: int, user: User | None) -> list[TagOut]:
    """Tags of a book ordered by vote score, then shelf weight. Score is the sum of votes."""
    score = func.coalesce(func.sum(TagVote.value), 0).label("score")
    rows = db.execute(
        select(Tag.id, Tag.name, BookTag.weight, score)
        .join(BookTag, BookTag.tag_id == Tag.id)
        .outerjoin(
            TagVote, and_(TagVote.book_id == BookTag.book_id, TagVote.tag_id == BookTag.tag_id)
        )
        .where(BookTag.book_id == book_id)
        .group_by(Tag.id, Tag.name, BookTag.weight)
        .order_by(score.desc(), BookTag.weight.desc(), Tag.name)
    ).all()
    my_votes: dict[int, int] = {}
    if user is not None:
        my_votes = {
            vote.tag_id: vote.value
            for vote in db.execute(
                select(TagVote.tag_id, TagVote.value).where(
                    TagVote.user_id == user.id, TagVote.book_id == book_id
                )
            )
        }
    return [
        TagOut(id=r.id, name=r.name, score=r.score, my_vote=my_votes.get(r.id, 0)) for r in rows
    ]
