"""Гибридный поиск по Qdrant: dense (e5) + sparse (BM25) с RRF-склейкой."""

import asyncio
import logging
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Document,
    FieldCondition,
    Filter as QdrantFilter,
    Fusion,
    FusionQuery,
    MatchAny,
    Prefetch,
)

from config import settings

logger = logging.getLogger("search")

_collection_client: AsyncQdrantClient | None = None
_embed_model = None

BM25_MODEL = "Qdrant/bm25"
MAX_FILTER_ITEMS = 50


def get_client() -> AsyncQdrantClient:
    global _collection_client
    if _collection_client is None:
        _collection_client = AsyncQdrantClient(
            host=settings.QDRANT_HOST, port=settings.QDRANT_PORT
        )
    return _collection_client


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer(settings.EMBEDDING_MODEL)
    return _embed_model


async def embed_query(text: str) -> list[float]:
    """Вектор запроса той же e5-моделью, что и в пайплайне (префикс 'query: ')."""
    model = _get_embed_model()
    raw = await asyncio.to_thread(
        lambda: model.encode([f"query: {text}"], normalize_embeddings=True).tolist()
    )
    return raw[0]


def _build_filter(exclude_tropes: list[str] | None, exclude_ids: list[int] | None):
    must_not = []
    if exclude_tropes:
        must_not.append(
            FieldCondition(key="tropes", match=MatchAny(any=list(exclude_tropes)[:MAX_FILTER_ITEMS]))
        )
    if exclude_ids:
        must_not.append(
            FieldCondition(key="source_idx", match=MatchAny(any=exclude_ids[:MAX_FILTER_ITEMS]))
        )
    return QdrantFilter(must_not=must_not) if must_not else None


def _to_cards(points: list[Any]) -> list[dict]:
    cards = []
    for p in points:
        payload = dict(p.payload or {})
        cards.append(
            {
                "source_idx": payload.get("source_idx"),
                "title": payload.get("title", ""),
                "author": payload.get("author", ""),
                "description": payload.get("description", ""),
                "genres": payload.get("genres", []) or [],
                "tropes": payload.get("tropes", []) or [],
                "score": getattr(p, "score", None),
            }
        )
    return cards


async def hybrid_search(
    query_text: str,
    *,
    exclude_tropes: list[str] | None = None,
    exclude_ids: list[int] | None = None,
    top_k: int | None = None,
    prefetch_k: int | None = None,
) -> list[dict]:
    """Dense+sparse prefetch + RRF fusion.

    Если коллекция ещё не пересоздана под гибридный индекс — падает с
    исключением, оркестратор переходит на dense-фолбэк.
    """
    top_k = top_k or settings.SEARCH_TOP_K
    prefetch_k = prefetch_k or settings.SEARCH_PREFETCH_K
    client = get_client()
    dense = await embed_query(query_text)
    qfilter = _build_filter(exclude_tropes, exclude_ids)

    resp = await client.query_points(
        collection_name=settings.QDRANT_COLLECTION,
        prefetch=[
            Prefetch(
                query=dense,
                using=settings.QDRANT_DENSE_NAME,
                limit=prefetch_k,
                filter=qfilter,
            ),
            Prefetch(
                query=Document(text=query_text, model=BM25_MODEL),
                using=settings.QDRANT_SPARSE_NAME,
                limit=prefetch_k,
                filter=qfilter,
            ),
        ],
        query=FusionQuery(fusion=Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )
    return _to_cards(resp.points)


async def dense_fallback(query_text: str, top_k: int | None = None) -> list[dict]:
    """Фолбэк без sparse: сначала по named dense, затем по безымянному вектору."""
    top_k = top_k or settings.SEARCH_TOP_K
    client = get_client()
    dense = await embed_query(query_text)
    try:
        resp = await client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=dense,
            using=settings.QDRANT_DENSE_NAME,
            limit=top_k,
            with_payload=True,
        )
    except Exception:
        resp = await client.query_points(
            collection_name=settings.QDRANT_COLLECTION,
            query=dense,
            limit=top_k,
            with_payload=True,
        )
    return _to_cards(resp.points)
