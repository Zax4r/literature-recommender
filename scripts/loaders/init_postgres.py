import psycopg

from scripts.config import DATABASE_URL

UPSERT_BOOK = """
INSERT INTO books (source_idx, title, author, description, genres, tropes)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (source_idx) DO UPDATE SET
    title = EXCLUDED.title, author = EXCLUDED.author,
    description = EXCLUDED.description,
    genres = EXCLUDED.genres, tropes = EXCLUDED.tropes;
"""


async def load_books_to_postgres(books: list[dict | None]) -> int:
    """Upsert карточек в books. source_idx = индекс в books.json/CSV.
    Предполагается, что миграции уже применены (alembic upgrade head)."""
    rows = [
        (i, b["title"], b["author"], b["description"],
         b.get("genres", []), b.get("tropes", []))
        for i, b in enumerate(books) if b is not None
    ]
    if not rows:
        return 0
    async with await psycopg.AsyncConnection.connect(DATABASE_URL) as conn:
        async with conn.cursor() as cur:
            await cur.executemany(UPSERT_BOOK, rows)
        await conn.commit()
    return len(rows)