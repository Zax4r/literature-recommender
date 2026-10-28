import asyncio
import hashlib
import json
import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    Document,
    Modifier,
    PointStruct,
    SparseVectorParams,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from scripts.config import (
    COLLECTION_NAME,
    DATA_DIR,
    EMBEDDING_MODEL,
    QDRANT_HOST,
    QDRANT_PORT,
    VECTOR_SIZE,
)

logger = logging.getLogger("qdrant")

DENSE_NAME = "dense"
SPARSE_NAME = "bm25"
BM25_MODEL = "Qdrant/bm25"

_model: SentenceTransformer | None = None

# Кэш эмбеддингов: source_idx -> {model, key, vector}.
# Лежит в scripts/data (смонтировано в контейнер), переживает перезапуски.
EMBEDDINGS_CACHE_FILE = DATA_DIR / "3_embeddings" / "embeddings.json"


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _text_for_card(b: dict) -> str:
    """e5-модели хотят префикс 'passage: ' на хранимых документах (dense)."""
    return f"passage: {b['title']}\n{b['description']}"


def _bm25_text_for_card(b: dict) -> str:
    """Keyword-текст для BM25: title + author + genres + tropes + description."""
    parts = [str(b["title"]), str(b.get("author") or "")]
    parts += [str(x) for x in (b.get("genres") or [])]
    parts += [str(x) for x in (b.get("tropes") or [])]
    parts.append(str(b.get("description") or ""))
    return "\n".join(p for p in parts if p)


def _avg_words(texts: list[str]) -> float:
    if not texts:
        return 10.0
    return sum(len(t.split()) for t in texts) / len(texts)


def _cache_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_cache() -> dict[str, dict]:
    if not EMBEDDINGS_CACHE_FILE.exists():
        return {}
    try:
        return json.loads(EMBEDDINGS_CACHE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, dict]) -> None:
    EMBEDDINGS_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = EMBEDDINGS_CACHE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(EMBEDDINGS_CACHE_FILE)


async def init_qdrant(recreate: bool = False) -> AsyncQdrantClient:
    """Создаёт коллекцию с dense + sparse(BM25, IDF) векторами.

    Старая dense-only коллекция автоматически пересоздаётся (self-heal);
    принудительно — параметром recreate=True. Идемпотентно.
    """
    client = AsyncQdrantClient(host=QDRANT_HOST, port=QDRANT_PORT)
    existing = {c.name for c in (await client.get_collections()).collections}

    needs_creation = COLLECTION_NAME not in existing
    if not needs_creation:
        try:
            info = await client.get_collection(COLLECTION_NAME)
            sparse = (info.config or {}).params.sparse_vectors or {}
            if SPARSE_NAME not in sparse:
                logger.warning(
                    "Коллекция %r не имеет sparse-вектор %r (нужен гибридный поиск) — пересоздаю",
                    COLLECTION_NAME, SPARSE_NAME,
                )
                needs_creation = True
        except Exception as exc:  # не смогли прочитать конфиг — пересоздаём
            logger.warning("Не удалось прочитать конфиг коллекции %r: %s", COLLECTION_NAME, exc)
            needs_creation = True

    if needs_creation or recreate:
        if COLLECTION_NAME in existing:
            await client.delete_collection(COLLECTION_NAME)
        await client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                DENSE_NAME: VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            },
            sparse_vectors_config={
                SPARSE_NAME: SparseVectorParams(modifier=Modifier.IDF),
            },
        )
        logger.info(
            "Коллекция %r создана: dense(%d, %s) + sparse(%s, IDF)",
            COLLECTION_NAME, VECTOR_SIZE, "COSINE", SPARSE_NAME,
        )
    return client


async def load_books_to_qdrant(books: list[dict | None], recreate: bool = False) -> int:
    client = await init_qdrant(recreate=recreate)
    cards = [(i, b) for i, b in enumerate(books) if b is not None]
    if not cards:
        await client.close()
        return 0

    texts = [_text_for_card(b) for _, b in cards]
    bm25_texts = [_bm25_text_for_card(b) for _, b in cards]
    avg_len = _avg_words(bm25_texts)
    cache = _load_cache()

    # Берём векторы из кэша, где текст и модель не менялись; остальные — в пересчёт.
    vectors: list[list[float] | None] = [None] * len(cards)
    missing: list[int] = []
    for n, (i, b) in enumerate(cards):
        entry = cache.get(str(i))
        if (
            entry
            and entry.get("model") == EMBEDDING_MODEL
            and entry.get("key") == _cache_key(texts[n])
        ):
            vectors[n] = entry["vector"]
        else:
            missing.append(n)

    if missing:
        new_vectors = await asyncio.to_thread(
            lambda: _get_model()
            .encode([texts[n] for n in missing], normalize_embeddings=True)
            .tolist()
        )
        for n, vec in zip(missing, new_vectors):
            vectors[n] = vec
            i, _ = cards[n]
            cache[str(i)] = {
                "model": EMBEDDING_MODEL,
                "key": _cache_key(texts[n]),
                "vector": vec,
            }
        _save_cache(cache)

    cached = len(cards) - len(missing)
    print(f"Эмбеддинги: из кэша {cached}, посчитано заново {len(missing)}")

    points = []
    for n, ((i, b), vec) in enumerate(zip(cards, vectors)):
        points.append(
            PointStruct(
                id=i,
                payload={**b, "source_idx": i},
                vector={
                    DENSE_NAME: vec,
                    SPARSE_NAME: Document(
                        text=bm25_texts[n],
                        model=BM25_MODEL,
                        options={"avg_len": avg_len},
                    ),
                },
            )
        )

    for start in range(0, len(points), 100):
        await client.upsert(
            collection_name=COLLECTION_NAME, points=points[start : start + 100]
        )
    await client.close()
    return len(points)
