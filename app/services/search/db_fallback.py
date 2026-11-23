"""Резервный поиск по каталогу в Postgres, если Qdrant недоступен.

Это не замена гибридному поиску: эмбеддинги и BM25 остаются основными.
Но если Qdrant упал или ещё не поднялся, чат не должен отвечать «книг нет» —
он ищет по словам в названии, авторе, описании, жанрах и тропах.
"""

import asyncio
import logging
import re
from typing import Any

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Book

logger = logging.getLogger("search")

_STOPWORDS = {
    "книга",
    "книгу",
    "книги",
    "книгой",
    "похожая",
    "похожее",
    "похожий",
    "похожие",
    "найти",
    "хочу",
    "хотел",
    "хотела",
    "про",
    "что",
    "чтобы",
    "где",
    "действие",
    "действия",
    "события",
    "событие",
    "который",
    "которая",
    "которые",
    "для",
    "мне",
    "можно",
    "посоветуй",
    "подбери",
    "произведение",
    "автор",
    "автора",
    "очень",
    "просто",
    "ещё",
    "еще",
    "если",
    "или",
    "без",
    "над",
    "под",
    "при",
    "это",
    "как",
    "так",
    "там",
    "тут",
}


def _split_terms(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for value in values or []:
        for part in re.split(r"[\s,;/]+", value.lower()):
            part = part.strip("«»\"'()[]")
            if len(part) >= 3 and part not in _STOPWORDS:
                out.append(part)
    return out


def build_terms(text: str | None, features: list[str] | None = None) -> list[str]:
    """Ключевые слова запроса: сначала признаки, затем слова пользователя."""
    terms = _split_terms(features)
    terms.extend(
        word for word in re.findall(r"[\wё-]{3,}", (text or "").lower()) if word not in _STOPWORDS
    )
    # Уникальные, в порядке появления, без разгона по длине.
    return list(dict.fromkeys(terms))[:16]


def _book_text(book: Book) -> str:
    return " ".join(
        [
            book.title or "",
            book.author or "",
            book.description or "",
            *(book.genres or []),
            *(book.tropes or []),
        ]
    ).lower()


def _to_card(book: Book, score: float) -> dict[str, Any]:
    return {
        "source_idx": book.source_idx,
        "title": book.title,
        "author": book.author or "",
        "description": book.description or "",
        "genres": book.genres or [],
        "tropes": book.tropes or [],
        "score": score,
    }


def _search_sync(
    text: str | None,
    features: list[str],
    exclude_ids: set[int],
    exclude_tropes: list[str],
    top_k: int,
) -> list[dict[str, Any]]:
    terms = build_terms(text, features)
    if not terms:
        return []

    banned_tropes = [t.strip().lower() for t in exclude_tropes if t.strip()]
    with SessionLocal() as db:
        books = list(db.scalars(select(Book)))

    scored: list[tuple[int, Book]] = []
    for book in books:
        if book.source_idx in exclude_ids:
            continue
        book_tropes = " ".join(book.tropes or []).lower()
        if banned_tropes and any(t in book_tropes for t in banned_tropes):
            continue
        text_blob = _book_text(book)
        hits = sum(1 for term in terms if term in text_blob)
        if hits:
            scored.append((hits, book))

    scored.sort(key=lambda pair: (-pair[0], pair[1].title))
    return [_to_card(book, hits / len(terms)) for hits, book in scored[:top_k]]


async def search_books(
    text: str | None,
    *,
    features: list[str] | None = None,
    exclude_ids: list[int] | None = None,
    exclude_tropes: list[str] | None = None,
    top_k: int = 6,
) -> list[dict[str, Any]]:
    """Ищет книги по словам в Postgres; вызывается только при сбое Qdrant."""
    return await asyncio.to_thread(
        _search_sync,
        text,
        list(features or []),
        set(exclude_ids or ()),
        list(exclude_tropes or []),
        top_k,
    )
