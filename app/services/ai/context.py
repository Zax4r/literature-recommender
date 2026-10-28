"""Связь чата с профилем пользователя: какие книги не стоит рекомендовать повторно."""

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Book, UserBook

UNWANTED_STATUSES = ("read", "reading", "dropped")


def _load_filtered(user_id: int) -> set[int]:
    with SessionLocal() as db:
        return set(
            db.scalars(
                select(Book.source_idx)
                .join(UserBook, UserBook.book_id == Book.id)
                .where(UserBook.user_id == user_id, UserBook.status.in_(UNWANTED_STATUSES))
            )
        )


async def get_filtered_book_ids(user_id: str | None) -> set[int]:
    """source_idx книг со статусами «прочитано», «читаю», «брошено» у пользователя."""
    if not user_id:
        return set()
    return await run_in_threadpool(_load_filtered, int(user_id))
