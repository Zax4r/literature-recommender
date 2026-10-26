from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import AdminUser, CurrentUser, DbSession, OptionalUser
from app.models import Author, Book, Favorite, User
from app.schemas.book import BookDetail, BookListItem, BookPage, ImportResult
from app.services import ucsd

router = APIRouter(prefix="/books", tags=["books"])

DESCRIPTION_PREVIEW_CHARS = 250

Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


def get_book_or_404(db: Session, book_id: int) -> Book:
    book = db.get(Book, book_id)
    if book is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Book not found")
    return book


def favorite_ids(db: Session, user: User | None, books: list[Book]) -> set[int]:
    if user is None or not books:
        return set()
    return set(
        db.scalars(
            select(Favorite.book_id).where(
                Favorite.user_id == user.id, Favorite.book_id.in_([b.id for b in books])
            )
        )
    )


def to_list_item(book: Book, favorites: set[int]) -> BookListItem:
    return BookListItem(
        id=book.id,
        title=book.title,
        authors=[a.name for a in book.authors],
        image_url=book.image_url,
        is_favorite=book.id in favorites,
    )


def to_page(items: list[BookListItem], total: int, offset: int, limit: int) -> BookPage:
    return BookPage(items=items, total=total, offset=offset, limit=limit)


@router.get("", response_model=BookPage)
def list_books(
    db: DbSession, user: OptionalUser, offset: Offset = 0, limit: Limit = 20
) -> BookPage:
    total = db.scalar(select(func.count()).select_from(Book)) or 0
    books = list(db.scalars(select(Book).order_by(Book.id).offset(offset).limit(limit)))
    favorites = favorite_ids(db, user, books)
    return to_page([to_list_item(b, favorites) for b in books], total, offset, limit)


@router.post("/import", response_model=ImportResult)
def import_books(
    _: AdminUser, db: DbSession, count: Annotated[int, Query(ge=1, le=1000)] = 100
) -> ImportResult:
    """Imports the first `count` usable UCSD Book Graph books, skipping known ones."""
    try:
        records = list(ucsd.fetch_books(count))
        author_ids = {a for r in records for a in r.author_ids}
        names = ucsd.fetch_author_names(author_ids)
    except OSError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"UCSD dataset unavailable: {exc}"
        ) from exc

    known = set(
        db.scalars(
            select(Book.goodreads_id).where(
                Book.goodreads_id.in_([r.goodreads_id for r in records])
            )
        )
    )
    authors = {
        a.goodreads_id: a
        for a in db.scalars(select(Author).where(Author.goodreads_id.in_(names.keys())))
    }
    for goodreads_id, name in names.items():
        if goodreads_id not in authors:
            authors[goodreads_id] = Author(goodreads_id=goodreads_id, name=name)

    new = [r for r in records if r.goodreads_id not in known]
    db.add_all(
        Book(
            goodreads_id=r.goodreads_id,
            title=r.title,
            description=r.description,
            image_url=r.image_url,
            url=r.url,
            authors=[authors[a] for a in r.author_ids if a in authors],
        )
        for r in new
    )
    db.commit()
    return ImportResult(imported=len(new), skipped=len(records) - len(new))


@router.get("/{book_id}", response_model=BookDetail)
def read_book(book_id: int, db: DbSession, user: OptionalUser) -> BookDetail:
    book = get_book_or_404(db, book_id)
    item = to_list_item(book, favorite_ids(db, user, [book]))
    return BookDetail(
        **item.model_dump(),
        description=book.description[:DESCRIPTION_PREVIEW_CHARS],
        url=book.url,
    )


@router.put("/{book_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def add_favorite(book_id: int, user: CurrentUser, db: DbSession) -> Response:
    get_book_or_404(db, book_id)
    if db.get(Favorite, (user.id, book_id)) is None:
        db.add(Favorite(user_id=user.id, book_id=book_id))
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{book_id}/favorite", status_code=status.HTTP_204_NO_CONTENT)
def remove_favorite(book_id: int, user: CurrentUser, db: DbSession) -> Response:
    favorite = db.get(Favorite, (user.id, book_id))
    if favorite is not None:
        db.delete(favorite)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
