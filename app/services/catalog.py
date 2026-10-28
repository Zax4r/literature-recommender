"""Каталог из коллекции Qdrant: те же книги, что ищет чат, видны в ленте."""

import hashlib
import logging
import re
import time
from typing import Any

from qdrant_client import QdrantClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models import Author, Book, BookTag, Tag
from config import settings

logger = logging.getLogger("catalog")

PAGE_SIZE = 500
MAX_TAGS_PER_BOOK = 10
WAIT_SECONDS = 10
WAIT_ATTEMPTS = 180  # Qdrant may still be filling while the API starts.


def _qdrant() -> QdrantClient:
    return QdrantClient(host=settings.QDRANT_HOST, port=settings.QDRANT_PORT, timeout=30)


def _tag_name(raw: str) -> str | None:
    name = re.sub(r"[^\w-]+", "-", raw.lower()).strip("-")
    return name if 2 <= len(name) <= 40 else None


def _author_id(name: str) -> str:
    return "qd-" + hashlib.md5(name.encode()).hexdigest()[:20]


def sync_from_qdrant(db: Session) -> tuple[int, int]:
    """Добавляет в каталог книги из Qdrant, которых ещё нет. Возвращает (добавлено, пропущено)."""
    client = _qdrant()
    known = set(db.scalars(select(Book.goodreads_id)))
    authors = {a.goodreads_id: a for a in db.scalars(select(Author))}
    tags = {t.name: t for t in db.scalars(select(Tag))}
    added = skipped = 0
    offset: Any = None

    while True:
        points, offset = client.scroll(
            settings.QDRANT_COLLECTION, limit=PAGE_SIZE, offset=offset, with_payload=True
        )
        for point in points:
            payload = point.payload or {}
            goodreads_id = f"qd-{point.id}"
            title = str(payload.get("title") or "").strip()
            if goodreads_id in known or not title:
                skipped += 1
                continue

            book_authors = []
            for name in str(payload.get("author") or "").split(";"):
                if not (name := name.strip()):
                    continue
                author_id = _author_id(name)
                if author_id not in authors:
                    authors[author_id] = Author(goodreads_id=author_id, name=name[:255])
                book_authors.append(authors[author_id])

            book = Book(
                goodreads_id=goodreads_id,
                title=title[:512],
                description=str(payload.get("description") or ""),
                image_url=None,
                url=None,
                authors=book_authors,
            )
            db.add(book)
            names = {
                n
                for raw in [*payload.get("genres", []), *payload.get("tropes", [])]
                if (n := _tag_name(str(raw)))
            }
            for name in sorted(names)[:MAX_TAGS_PER_BOOK]:
                tag = tags.get(name)
                if tag is None:
                    tag = tags[name] = Tag(name=name)
                db.add(BookTag(book=book, tag=tag, weight=1))
            added += 1
        db.commit()
        if offset is None:
            return added, skipped


def sync_when_ready() -> None:
    """Фоновая задача старта: заполняет пустой каталог, как только Qdrant загружен."""
    try:
        for _ in range(WAIT_ATTEMPTS):
            with SessionLocal() as db:
                if db.scalar(select(func.count()).select_from(Book)):
                    return
                try:
                    if _qdrant().count(settings.QDRANT_COLLECTION).count:
                        added, _ = sync_from_qdrant(db)
                        logger.info("Catalog filled from Qdrant: %d books", added)
                        return
                except Exception as exc:  # noqa: BLE001
                    logger.info("Qdrant is not ready yet: %s", exc)
            time.sleep(WAIT_SECONDS)
    except Exception:
        logger.exception("Catalog sync failed")
