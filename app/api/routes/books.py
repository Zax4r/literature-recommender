from typing import Annotated

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, OptionalUser
from app.models import Book, Favorite
from app.schemas.book import BookDetail, BookPage
from app.services.books import book_tags, get_book_or_404, store_url, to_list_items

router = APIRouter(prefix="/books", tags=["books"])

DESCRIPTION_PREVIEW_CHARS = 250

Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=100)]


@router.get("", response_model=BookPage)
def list_books(
    db: DbSession, user: OptionalUser, offset: Offset = 0, limit: Limit = 20
) -> BookPage:
    total = db.scalar(select(func.count()).select_from(Book)) or 0
    books = list(db.scalars(select(Book).order_by(Book.id).offset(offset).limit(limit)))
    return BookPage(items=to_list_items(db, user, books), total=total, offset=offset, limit=limit)


@router.get("/{book_id}", response_model=BookDetail)
def read_book(book_id: int, db: DbSession, user: OptionalUser) -> BookDetail:
    book = get_book_or_404(db, book_id)
    item = to_list_items(db, user, [book])[0]
    return BookDetail(
        **item.model_dump(),
        description=book.description[:DESCRIPTION_PREVIEW_CHARS],
        genres=book.genres,
        tropes=book.tropes,
        store_url=store_url(book),
        tags=book_tags(db, book.id, user),
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
