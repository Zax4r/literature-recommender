from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlalchemy import func, select

from app.api.deps import AdminUser, CurrentUser, DbSession, OptionalUser
from app.models import Author, Book, BookTag, Favorite, Tag
from app.schemas.book import BookDetail, BookPage, ImportResult
from app.services import catalog, ucsd
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

    tag_names = {name for r in records for name, _count in r.shelves}
    tags = {t.name: t for t in db.scalars(select(Tag).where(Tag.name.in_(tag_names)))}
    for name in tag_names - tags.keys():
        tags[name] = Tag(name=name)

    new = [r for r in records if r.goodreads_id not in known]
    for r in new:
        book = Book(
            goodreads_id=r.goodreads_id,
            title=r.title,
            description=r.description,
            image_url=r.image_url,
            url=r.url,
            authors=[authors[a] for a in r.author_ids if a in authors],
        )
        db.add(book)
        db.add_all(BookTag(book=book, tag=tags[name], weight=count) for name, count in r.shelves)
    db.commit()
    return ImportResult(imported=len(new), skipped=len(records) - len(new))


@router.post("/sync", response_model=ImportResult)
def sync_catalog(_: AdminUser, db: DbSession) -> ImportResult:
    """Adds the books stored in Qdrant (the ones the chat recommends) to the catalog."""
    try:
        imported, skipped = catalog.sync_from_qdrant(db)
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Qdrant unavailable: {exc}") from exc
    return ImportResult(imported=imported, skipped=skipped)


@router.get("/{book_id}", response_model=BookDetail)
def read_book(book_id: int, db: DbSession, user: OptionalUser) -> BookDetail:
    book = get_book_or_404(db, book_id)
    item = to_list_items(db, user, [book])[0]
    return BookDetail(
        **item.model_dump(),
        description=book.description[:DESCRIPTION_PREVIEW_CHARS],
        url=book.url,
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
